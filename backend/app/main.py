"""FastAPI application for CalSync."""
from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, apply_schema_upgrades, engine
from .models import (
    Account,
    AccountType,
    EventResponseStatus,
    EventStatus,
    ImapFolder,
    SyncMapping,
    TrackedEvent,
)
from .schemas import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    ConnectionTestRequest,
    ConnectionTestResult,
    ConflictResolutionOption,
    ConflictDifference,
    ManualSyncMissingDetail,
    ManualSyncRequest,
    ManualSyncResponse,
    EventResponseUpdate,
    AutoSyncRequest,
    AutoSyncStatus,
    SyncConflictDetails,
    SyncJobStatus,
    SyncMappingCreate,
    SyncMappingRead,
    SyncMappingUpdate,
    TrackedEventRead,
)
from .services import event_processor
from .services.caldav_client import (
    CalDavConnection,
    CalDavSettings,
    find_conflicting_events,
    list_calendars,
)
from .services.imap_client import FolderSelection, ImapSettings, fetch_calendar_candidates
from .services.job_tracker import job_tracker
from .services.scheduler import scheduler
from .utils.ics_parser import extract_event_snapshot, merge_histories, parse_ics_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

Base.metadata.create_all(bind=engine)

apply_schema_upgrades()

app = FastAPI(title="CalSync", version="0.1.0")

AUTO_SYNC_JOB_ID = "auto-sync"
auto_sync_preferences: Dict[str, Any] = {
    "auto_response": EventResponseStatus.NONE,
    "interval_minutes": 5,
}
_auto_sync_state: Dict[str, Optional[str]] = {"job_id": None}
_auto_sync_lock = Lock()


def _active_auto_sync_job() -> Optional[SyncJobStatus]:
    """Return the status of the currently running auto-sync job, if any."""

    with _auto_sync_lock:
        job_id = _auto_sync_state.get("job_id")
    if not job_id:
        return None
    state = job_tracker.get(job_id)
    if state is None:
        return None
    return state.to_status()


def _ensure_timezone(value: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetimes are timezone aware to keep CalDAV searches stable."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _event_search_window(event: TrackedEvent) -> tuple[Optional[datetime], Optional[datetime]]:
    """Calculate a safe search window for conflict detection."""
    start = event.start or event.end
    end = event.end or event.start
    start = _ensure_timezone(start)
    end = _ensure_timezone(end)
    if start is None:
        return None, None
    if end is None or end <= start:
        end = start + timedelta(minutes=30)
    return start, end


def _normalize_history(event: TrackedEvent) -> Tuple[List[Dict[str, str]], bool]:
    """Ensure history entries are returned as clean dictionaries."""

    raw_history = getattr(event, "history", [])
    changed = False

    if isinstance(raw_history, str):
        try:
            raw_history = json.loads(raw_history)
        except JSONDecodeError:
            logger.warning("History for event %s is not valid JSON, dropping.", event.id)
            return [], True
        changed = True

    if not isinstance(raw_history, list):
        if raw_history not in (None, []):
            logger.warning(
                "History for event %s has unexpected type %s, resetting.",
                event.id,
                type(raw_history).__name__,
            )
        return [], raw_history not in (None, [])

    normalized: List[Dict[str, str]] = []
    for entry in raw_history:
        if not isinstance(entry, dict):
            logger.warning(
                "Skipping non-dict history entry for event %s: %r",
                event.id,
                entry,
            )
            changed = True
            continue
        timestamp = entry.get("timestamp")
        action = entry.get("action")
        description = entry.get("description")
        if not isinstance(timestamp, str) or not isinstance(action, str) or not isinstance(description, str):
            logger.warning(
                "Skipping malformed history entry for event %s: %r",
                event.id,
                entry,
            )
            changed = True
            continue
        normalized.append({
            "timestamp": timestamp,
            "action": action,
            "description": description,
        })

    if len(normalized) != len(raw_history):
        changed = True

    return normalized, changed


def _normalize_histories(events: List[TrackedEvent], db: Session) -> None:
    """Coerce legacy or malformed history payloads to the expected structure."""

    changed_histories: Dict[int, List[Dict[str, str]]] = {}
    for event in events:
        history, changed = _normalize_history(event)
        if changed:
            event.history = history
            if event.id is not None:
                changed_histories[event.id] = history
    if changed_histories:
        try:
            with SessionLocal() as writer:
                writer.bulk_update_mappings(
                    TrackedEvent,
                    [
                        {"id": event_id, "history": history}
                        for event_id, history in changed_histories.items()
                    ],
                )
                writer.commit()
        except Exception:
            logger.exception("Failed to persist normalized history entries")


def _attach_conflicts(events: List[TrackedEvent], db: Session) -> None:
    """Enrich tracked events with CalDAV conflict information."""
    if not events:
        return
    for event in events:
        setattr(event, "conflicts", [])

    mappings = db.execute(select(SyncMapping)).scalars().all()
    mapping_index = {
        (mapping.imap_account_id, mapping.imap_folder): mapping for mapping in mappings
    }
    grouped: Dict[int, Dict[str, Any]] = {}
    for event in events:
        if event.source_account_id is None or not event.source_folder:
            continue
        mapping = mapping_index.get((event.source_account_id, event.source_folder))
        if mapping is None:
            continue
        group = grouped.setdefault(mapping.id, {"mapping": mapping, "events": []})
        group["events"].append(event)

    if not grouped:
        return

    account_cache: Dict[int, Account] = {}
    for group in grouped.values():
        mapping: SyncMapping = group["mapping"]
        events_for_mapping: List[TrackedEvent] = group["events"]
        account = account_cache.get(mapping.caldav_account_id)
        if account is None:
            account = db.get(Account, mapping.caldav_account_id)
            if account is None:
                logger.warning(
                    "CalDAV account %s not found for mapping %s",
                    mapping.caldav_account_id,
                    mapping.id,
                )
                continue
            account_cache[mapping.caldav_account_id] = account
        try:
            settings = CalDavSettings(**account.settings)
        except TypeError:
            logger.exception(
                "Ungültige CalDAV Einstellungen für Konto %s", account.id
            )
            continue
        try:
            with CalDavConnection(settings) as client:
                calendar = client.principal().calendar(cal_url=mapping.calendar_url)
                windows: List[Tuple[TrackedEvent, datetime, datetime]] = []
                for event in events_for_mapping:
                    start, end = _event_search_window(event)
                    if start is None or end is None:
                        continue
                    windows.append((event, start, end))

                if not windows:
                    continue

                overall_start = min(start for _, start, _ in windows)
                overall_end = max(end for _, _, end in windows)
                logger.debug(
                    "Prüfe Konflikte für Mapping %s (%s Events) im Zeitraum %s bis %s",
                    mapping.id,
                    len(windows),
                    overall_start,
                    overall_end,
                )

                candidates = find_conflicting_events(calendar, overall_start, overall_end)
                parsed_candidates: List[Tuple[Dict[str, Any], datetime, datetime]] = []
                for candidate in candidates:
                    start_raw = candidate.get("start")
                    end_raw = candidate.get("end")
                    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
                        logger.warning(
                            "Konflikt ohne gültige Zeitangaben für Mapping %s übersprungen: %s",
                            mapping.id,
                            candidate,
                        )
                        continue
                    try:
                        cand_start = datetime.fromisoformat(start_raw)
                        cand_end = datetime.fromisoformat(end_raw)
                    except ValueError:
                        logger.warning(
                            "Konnte Konfliktzeiten nicht parsen für Mapping %s: %s",
                            mapping.id,
                            candidate,
                        )
                        continue
                    cand_start = _ensure_timezone(cand_start)
                    cand_end = _ensure_timezone(cand_end)
                    parsed_candidates.append((candidate, cand_start, cand_end))

                for event, start, end in windows:
                    conflicts_for_event: List[Dict[str, Any]] = []
                    for candidate, cand_start, cand_end in parsed_candidates:
                        if candidate.get("uid") == event.uid:
                            continue
                        if cand_start >= end or cand_end <= start:
                            continue
                        conflicts_for_event.append(candidate)
                    if conflicts_for_event:
                        setattr(event, "conflicts", conflicts_for_event)
        except Exception:
            logger.exception(
                "Konfliktprüfung für Mapping %s fehlgeschlagen", mapping.id
            )
            continue


def _serialize_timestamp(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    target = value
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    else:
        target = target.astimezone(timezone.utc)
    return target.isoformat()


def _build_conflict_details(event: TrackedEvent) -> Optional[SyncConflictDetails]:
    if not event.sync_conflict:
        return None

    remote_snapshot = {}
    if isinstance(event.sync_conflict_snapshot, dict):
        remote_snapshot = event.sync_conflict_snapshot

    local_snapshot: Optional[dict] = None
    if event.payload:
        try:
            local_snapshot = extract_event_snapshot(event.payload, uid=event.uid)
        except Exception:
            logger.exception(
                "Konfliktdetails konnten nicht aus lokaler Payload gelesen werden: %s",
                event.uid,
            )

    local_values: Dict[str, Optional[str]] = {
        "summary": event.summary,
        "organizer": event.organizer,
        "start": _serialize_timestamp(event.start),
        "end": _serialize_timestamp(event.end),
        "location": None,
        "description": None,
    }

    if local_snapshot:
        for key in ("summary", "organizer", "start", "end", "location", "description"):
            value = local_snapshot.get(key)
            if value is not None:
                local_values[key] = str(value)

    differences: List[ConflictDifference] = []
    label_map = {
        "summary": "Titel",
        "start": "Beginn",
        "end": "Ende",
        "organizer": "Organisator",
        "location": "Ort",
        "description": "Beschreibung",
    }

    for field, label in label_map.items():
        local_value = local_values.get(field)
        remote_value_raw = remote_snapshot.get(field)
        remote_value = str(remote_value_raw) if remote_value_raw is not None else None
        if not (local_value or remote_value):
            continue
        if local_value == remote_value:
            continue
        differences.append(
            ConflictDifference(
                field=field,
                label=label,
                local_value=local_value,
                remote_value=remote_value,
            )
        )

    suggestions: List[ConflictResolutionOption] = [
        ConflictResolutionOption(
            action="retry-sync",
            label="E-Mail-Import erneut synchronisieren",
            description="Prüfe die Daten aus dem E-Mail-Import und starte anschließend eine neue Synchronisation, sobald der Konflikt behoben ist.",
        ),
        ConflictResolutionOption(
            action="apply-remote",
            label="Kalenderdaten übernehmen",
            description="Übernehme die Anpassungen aus den Kalenderdaten manuell oder importiere die ICS-Daten, um beide Stände anzugleichen.",
        ),
        ConflictResolutionOption(
            action="disable-tracking",
            label="Termin nicht mehr verfolgen",
            description="Blendet den Termin dauerhaft in CalSync aus und stoppt die automatische Synchronisation.",
            interactive=True,
            requires_confirmation=True,
        ),
    ]

    return SyncConflictDetails(differences=differences, suggestions=suggestions)


def _attach_sync_state(events: List[TrackedEvent]) -> None:
    """Expose synchronization metadata for API responses."""

    for event in events:
        conflict_details = _build_conflict_details(event)
        setattr(
            event,
            "sync_state",
            {
                "local_version": event.local_version or 0,
                "synced_version": event.synced_version or 0,
                "has_conflict": bool(event.sync_conflict),
                "conflict_reason": event.sync_conflict_reason,
                "local_last_modified": event.local_last_modified,
                "remote_last_modified": event.remote_last_modified,
                "last_modified_source": event.last_modified_source,
                "caldav_etag": event.caldav_etag,
                "conflict_details": conflict_details.model_dump()
                if conflict_details
                else None,
            },
        )


def _folder_selections(account: Account) -> List[FolderSelection]:
    """Build the folder selection list for an IMAP account."""

    selections = [
        FolderSelection(name=folder.name, include_subfolders=folder.include_subfolders)
        for folder in account.imap_folders
    ]
    if not selections:
        selections.append(FolderSelection(name="INBOX"))
    return selections


def perform_mail_scan(
    db: Session, progress_callback: Optional[Callable[[int, int], None]] = None
) -> tuple[int, int]:
    """Scan configured IMAP folders and store discovered events."""

    accounts = (
        db.execute(select(Account).where(Account.type == AccountType.IMAP)).scalars().all()
    )
    messages_processed = 0
    events_imported = 0

    for account in accounts:
        try:
            settings = ImapSettings(**account.settings)
        except TypeError:
            logger.exception("Ungültige IMAP Einstellungen für Konto %s", account.id)
            continue

        folder_configs = _folder_selections(account)

        def folder_progress(processed_delta: int, total_delta: int) -> None:
            if progress_callback is not None:
                progress_callback(processed_delta, total_delta)

        candidates = fetch_calendar_candidates(
            settings, folder_configs, progress_callback=folder_progress
        )
        for candidate in candidates:
            messages_processed += 1
            for attachment in candidate.attachments:
                parsed_events = parse_ics_payload(attachment.payload)
                stored = event_processor.upsert_events(
                    parsed_events,
                    candidate.message_id,
                    source_account_id=account.id,
                    source_folder=candidate.folder,
                )
                events_imported += len(stored)

    return messages_processed, events_imported


def _execute_scan_job(job_id: str) -> None:
    """Background execution for mailbox scans with progress updates."""

    logger.info("Starting mailbox scan job %s", job_id)
    job_tracker.update(
        job_id,
        status="running",
        processed=0,
        total=0,
        detail={
            "phase": "Postfach-Scan",
            "description": "Postfächer werden analysiert…",
            "processed": 0,
            "total": 0,
        },
    )

    try:
        with SessionLocal() as session:
            progress_state = {"processed": 0, "total": 0}

            def progress(processed_delta: int, total_delta: int) -> None:
                if total_delta:
                    job_tracker.increment(job_id, total_delta=total_delta)
                    progress_state["total"] += total_delta
                if processed_delta:
                    job_tracker.increment(job_id, processed_delta=processed_delta)
                    progress_state["processed"] += processed_delta
                job_tracker.update(
                    job_id,
                    detail={
                        "phase": "Postfach-Scan",
                        "description": "Postfächer werden analysiert…",
                        "processed": progress_state["processed"],
                        "total": progress_state["total"],
                    },
                )

            messages, events = perform_mail_scan(session, progress_callback=progress)

        job_tracker.update(job_id, processed=messages)
        job_tracker.finish(
            job_id,
            detail={
                "messages_processed": messages,
                "events_imported": events,
                "phase": "Postfach-Scan",
                "description": "Scan abgeschlossen",
            },
        )
    except Exception:
        logger.exception("Mailbox scan job %s failed", job_id)
        job_tracker.fail(job_id, "Postfach-Scan fehlgeschlagen.")


def _execute_manual_sync_job(job_id: str, event_ids: List[int]) -> None:
    """Background execution for manual sync requests."""

    logger.info("Starting manual sync job %s", job_id)
    total = len(event_ids)
    job_tracker.update(
        job_id,
        status="running",
        processed=0,
        total=total,
        detail={
            "phase": "Prüfung",
            "description": "Terminauswahl wird geprüft…",
            "processed": 0,
            "total": total,
        },
    )

    processed = 0
    missing: List[ManualSyncMissingDetail] = []
    uploaded: List[str] = []

    try:
        if total == 0:
            result = ManualSyncResponse(uploaded=[], missing=[])
            job_tracker.finish(job_id, detail=result.model_dump())
            return

        with SessionLocal() as session:
            events = (
                session.execute(
                    select(TrackedEvent).where(TrackedEvent.id.in_(event_ids))
                )
                .scalars()
                .all()
            )

            if not events:
                job_tracker.fail(job_id, "Keine passenden Termine gefunden")
                return

            sync_groups: Dict[int, Dict[str, Any]] = {}

            for event in events:
                if event.tracking_disabled:
                    logger.info(
                        "Skipping manual sync for %s because tracking is disabled", event.uid
                    )
                    missing.append(
                        ManualSyncMissingDetail(
                            event_id=event.id,
                            uid=event.uid,
                            account_id=event.source_account_id,
                            folder=event.source_folder,
                            reason="Tracking für diesen Termin wurde deaktiviert",
                        )
                    )
                    processed += 1
                    job_tracker.update(
                        job_id,
                        processed=processed,
                        detail={
                            "phase": "Prüfung",
                            "description": "Terminauswahl wird geprüft…",
                            "processed": processed,
                            "total": total,
                        },
                    )
                    continue
                if event.sync_conflict:
                    logger.info(
                        "Skipping manual sync for %s due to existing conflict", event.uid
                    )
                    missing.append(
                        ManualSyncMissingDetail(
                            event_id=event.id,
                            uid=event.uid,
                            account_id=event.source_account_id,
                            folder=event.source_folder,
                            reason="Synchronisationskonflikt muss zuerst gelöst werden",
                        )
                    )
                    processed += 1
                    job_tracker.update(
                        job_id,
                        processed=processed,
                        detail={
                            "phase": "Prüfung",
                            "description": "Terminauswahl wird geprüft…",
                            "processed": processed,
                            "total": total,
                        },
                    )
                    continue
                if event.source_account_id is None or not event.source_folder:
                    missing.append(
                        ManualSyncMissingDetail(
                            event_id=event.id,
                            uid=event.uid,
                            account_id=event.source_account_id,
                            folder=event.source_folder,
                            reason="Keine Quellinformationen vorhanden",
                        )
                    )
                    processed += 1
                    job_tracker.update(
                        job_id,
                        processed=processed,
                        detail={
                            "phase": "Prüfung",
                            "description": "Terminauswahl wird geprüft…",
                            "processed": processed,
                            "total": total,
                        },
                    )
                    continue

                mapping = (
                    session.execute(
                        select(SyncMapping)
                        .where(SyncMapping.imap_account_id == event.source_account_id)
                        .where(SyncMapping.imap_folder == event.source_folder)
                    )
                    .scalars()
                    .first()
                )

                if mapping is None:
                    missing.append(
                        ManualSyncMissingDetail(
                            event_id=event.id,
                            uid=event.uid,
                            account_id=event.source_account_id,
                            folder=event.source_folder,
                            reason="Keine Sync-Zuordnung für Konto und Ordner",
                        )
                    )
                    processed += 1
                    job_tracker.update(
                        job_id,
                        processed=processed,
                        detail={
                            "phase": "Prüfung",
                            "description": "Terminauswahl wird geprüft…",
                            "processed": processed,
                            "total": total,
                        },
                    )
                    continue

                caldav_account = session.get(Account, mapping.caldav_account_id)
                if caldav_account is None or caldav_account.type != AccountType.CALDAV:
                    missing.append(
                        ManualSyncMissingDetail(
                            event_id=event.id,
                            uid=event.uid,
                            account_id=event.source_account_id,
                            folder=event.source_folder,
                            reason="Zugeordnetes CalDAV-Konto nicht gefunden",
                        )
                    )
                    processed += 1
                    job_tracker.update(
                        job_id,
                        processed=processed,
                        detail={
                            "phase": "Prüfung",
                            "description": "Terminauswahl wird geprüft…",
                            "processed": processed,
                            "total": total,
                        },
                    )
                    continue

                try:
                    settings = CalDavSettings(**caldav_account.settings)
                except TypeError as exc:
                    logger.exception(
                        "CalDAV settings invalid for account %s", caldav_account.id
                    )
                    missing.append(
                        ManualSyncMissingDetail(
                            event_id=event.id,
                            uid=event.uid,
                            account_id=event.source_account_id,
                            folder=event.source_folder,
                            reason=f"Ungültige CalDAV Einstellungen: {exc}",
                        )
                    )
                    processed += 1
                    job_tracker.update(
                        job_id,
                        processed=processed,
                        detail={
                            "phase": "Prüfung",
                            "description": "Terminauswahl wird geprüft…",
                            "processed": processed,
                            "total": total,
                        },
                    )
                    continue

                group = sync_groups.setdefault(
                    mapping.id,
                    {"events": [], "mapping": mapping, "settings": settings},
                )
                group["events"].append(event)

            def progress(event: TrackedEvent, success: bool) -> None:
                nonlocal processed
                processed += 1
                title = event.summary or event.uid
                job_tracker.update(
                    job_id,
                    processed=processed,
                    detail={
                        "phase": "Synchronisation",
                        "description": f"Übertrage \"{title}\"",
                        "processed": processed,
                        "total": total,
                    },
                )

            for group in sync_groups.values():
                mapping: SyncMapping = group["mapping"]
                settings: CalDavSettings = group["settings"]
                events_for_mapping: List[TrackedEvent] = group["events"]
                job_tracker.update(
                    job_id,
                    detail={
                        "phase": "Synchronisation",
                        "description": f"Synchronisiere {len(events_for_mapping)} Termine mit {mapping.calendar_name or mapping.calendar_url}",
                        "processed": processed,
                        "total": total,
                    },
                )
                uploaded.extend(
                    event_processor.sync_events_to_calendar(
                        events_for_mapping,
                        mapping.calendar_url,
                        settings,
                        progress_callback=progress,
                    )
                )

        result = ManualSyncResponse(uploaded=uploaded, missing=missing)
        job_tracker.finish(job_id, detail=result.model_dump())
    except Exception:
        logger.exception("Manual sync job %s failed", job_id)
        job_tracker.fail(job_id, "Synchronisation fehlgeschlagen.")


def _execute_sync_all_job(job_id: str) -> None:
    """Background execution for syncing all pending events."""

    logger.info("Starting sync-all job %s", job_id)
    job_tracker.update(
        job_id,
        status="running",
        processed=0,
        total=0,
        detail={
            "phase": "Synchronisation",
            "description": "Kalenderabgleich läuft…",
            "processed": 0,
            "total": 0,
        },
    )
    processed = 0
    progress_state = {"total": 0}

    def progress(processed_delta: int, total_delta: int) -> None:
        nonlocal processed
        if total_delta:
            job_tracker.increment(job_id, total_delta=total_delta)
            progress_state["total"] += total_delta
        if processed_delta:
            processed += processed_delta
            job_tracker.update(
                job_id,
                processed=processed,
                detail={
                    "phase": "Synchronisation",
                    "description": "Kalenderabgleich läuft…",
                    "processed": processed,
                    "total": progress_state["total"],
                },
            )

    try:
        with SessionLocal() as session:
            uploaded = perform_sync_all(session, progress_callback=progress)
        job_tracker.finish(
            job_id,
            detail={
                "uploaded": uploaded,
                "phase": "Synchronisation",
                "description": "Kalenderabgleich abgeschlossen",
            },
        )
    except Exception:
        logger.exception("Sync-all job %s failed", job_id)
        job_tracker.fail(job_id, "Synchronisation fehlgeschlagen.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    scheduler.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    scheduler.shutdown()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/accounts", response_model=List[AccountRead])
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.execute(select(Account)).scalars().all()
    return accounts


@app.post("/accounts", response_model=AccountRead)
def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    db_account = Account(
        label=account.label,
        type=account.type,
        settings=account.settings,
    )
    db.add(db_account)
    db.flush()
    for folder in account.imap_folders:
        db.add(
            ImapFolder(
                account_id=db_account.id,
                name=folder.name,
                include_subfolders=folder.include_subfolders,
            )
        )
    db.commit()
    db.refresh(db_account)
    return db_account


@app.put("/accounts/{account_id}", response_model=AccountRead)
def update_account(account_id: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    db_account = db.get(Account, account_id)
    if db_account is None:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")

    db_account.label = payload.label
    db_account.type = payload.type
    db_account.settings = payload.settings
    if payload.type == AccountType.IMAP:
        db_account.imap_folders = [
            ImapFolder(
                name=folder.name,
                include_subfolders=folder.include_subfolders,
            )
            for folder in payload.imap_folders
        ]
    else:
        db_account.imap_folders = []

    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    logger.info("Updated account %s", account_id)
    return db_account


@app.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")

    logger.info("Deleting account %s", account_id)
    mappings = (
        db.execute(
            select(SyncMapping).where(
                or_(
                    SyncMapping.imap_account_id == account_id,
                    SyncMapping.caldav_account_id == account_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for mapping in mappings:
        db.delete(mapping)

    events = (
        db.execute(select(TrackedEvent).where(TrackedEvent.source_account_id == account_id))
        .scalars()
        .all()
    )
    for event in events:
        event.source_account_id = None
        db.add(event)

    db.delete(account)
    db.commit()
    return {"deleted": True}


@app.post("/accounts/test", response_model=ConnectionTestResult)
def test_connection(payload: ConnectionTestRequest) -> ConnectionTestResult:
    try:
        if payload.type == AccountType.IMAP:
            folders = payload.settings.get("folders", ["INBOX"])
            settings = ImapSettings(
                host=payload.settings["host"],
                username=payload.settings["username"],
                password=payload.settings["password"],
                ssl=payload.settings.get("ssl", True),
                port=payload.settings.get("port"),
            )
            fetch_calendar_candidates(settings, folders)
            return ConnectionTestResult(success=True, message="IMAP connection successful")
        if payload.type == AccountType.CALDAV:
            settings = CalDavSettings(
                url=payload.settings["url"],
                username=payload.settings.get("username"),
                password=payload.settings.get("password"),
            )
            calendars = list(list_calendars(settings))
            return ConnectionTestResult(
                success=True,
                message="CalDAV connection successful",
                details={"calendars": calendars},
            )
    except Exception as exc:  # pragma: no cover - direct user feedback
        logger.exception("Connection test failed")
        return ConnectionTestResult(success=False, message=str(exc))
    raise HTTPException(status_code=400, detail="Unsupported account type")


@app.get("/events", response_model=List[TrackedEventRead])
def list_events(db: Session = Depends(get_db)):
    events = (
        db.execute(select(TrackedEvent).where(TrackedEvent.tracking_disabled.is_(False)))
        .scalars()
        .all()
    )
    _normalize_histories(events, db)
    _attach_conflicts(events, db)
    _attach_sync_state(events)
    return events


@app.post("/events/scan", response_model=SyncJobStatus)
def scan_mailboxes(background_tasks: BackgroundTasks):
    state = job_tracker.create("scan", total=0)
    job_tracker.update(state.job_id, status="running", processed=0, total=0)
    background_tasks.add_task(_execute_scan_job, state.job_id)
    return state.to_status()


@app.post("/events/manual-sync", response_model=SyncJobStatus)
def manual_sync(
    payload: ManualSyncRequest, background_tasks: BackgroundTasks
) -> SyncJobStatus:
    state = job_tracker.create("manual-sync", total=len(payload.event_ids))
    if not payload.event_ids:
        job_tracker.finish(state.job_id, detail=ManualSyncResponse(uploaded=[], missing=[]).model_dump())
        return state.to_status()

    job_tracker.update(
        state.job_id,
        status="running",
        processed=0,
        total=len(payload.event_ids),
    )
    background_tasks.add_task(_execute_manual_sync_job, state.job_id, payload.event_ids)
    return state.to_status()


@app.post("/events/{event_id}/response", response_model=TrackedEventRead)
def update_event_response(
    event_id: int, payload: EventResponseUpdate, db: Session = Depends(get_db)
) -> TrackedEvent:
    event = db.get(TrackedEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Termin nicht gefunden")

    response = payload.response
    event.response_status = response
    if event.status != EventStatus.CANCELLED:
        event.status = EventStatus.UPDATED
    description_map = {
        EventResponseStatus.ACCEPTED: "Teilnahme zugesagt",
        EventResponseStatus.TENTATIVE: "Teilnahme auf vielleicht gesetzt",
        EventResponseStatus.DECLINED: "Teilnahme abgesagt",
        EventResponseStatus.NONE: "Antwort zurückgesetzt",
    }
    event_processor.annotate_response(event)
    event.history = merge_histories(
        event.history or [],
        {
            "timestamp": datetime.utcnow().isoformat(),
            "action": "response",
            "description": description_map.get(response, "Teilnahmestatus aktualisiert"),
        },
    )
    event.local_version = (event.local_version or 0) + 1
    event.local_last_modified = datetime.utcnow()
    event.last_modified_source = "local"
    event.sync_conflict = False
    event.sync_conflict_reason = None
    mapping: Optional[SyncMapping] = None
    caldav_settings: Optional[CalDavSettings] = None
    if event.source_account_id and event.source_folder:
        mapping = (
            db.execute(
                select(SyncMapping)
                .where(SyncMapping.imap_account_id == event.source_account_id)
                .where(SyncMapping.imap_folder == event.source_folder)
            )
            .scalars()
            .first()
        )
        if mapping is not None:
            caldav_account = db.get(Account, mapping.caldav_account_id)
            if caldav_account is None:
                logger.warning(
                    "CalDAV account %s nicht gefunden für Mapping %s",
                    mapping.caldav_account_id,
                    mapping.id,
                )
            else:
                try:
                    caldav_settings = CalDavSettings(**caldav_account.settings)
                except TypeError:
                    logger.exception(
                        "Ungültige CalDAV Einstellungen für Konto %s", caldav_account.id
                    )
                    caldav_settings = None

    db.add(event)
    db.commit()
    db.refresh(event)
    logger.info("Updated response for event %s to %s", event.uid, response.value)
    if mapping and caldav_settings:
        try:
            event_processor.sync_events_to_calendar(
                [event], mapping.calendar_url, caldav_settings
            )
        except Exception:
            logger.exception(
                "Failed to sync event %s after response update", event.uid
            )
        finally:
            db.refresh(event)
    else:
        logger.info(
            "Kalendersync für Termin %s übersprungen (fehlendes Mapping oder Einstellungen)",
            event.uid,
        )
    _attach_conflicts([event], db)
    _attach_sync_state([event])
    return event


@app.post("/events/{event_id}/disable-tracking", response_model=TrackedEventRead)
def disable_event_tracking(event_id: int, db: Session = Depends(get_db)) -> TrackedEvent:
    event = db.get(TrackedEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Termin nicht gefunden")

    if not event.tracking_disabled:
        event.tracking_disabled = True
        event.sync_conflict = False
        event.sync_conflict_reason = "Tracking deaktiviert"
        event.sync_conflict_snapshot = None
        event.history = merge_histories(
            event.history or [],
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": "tracking-disabled",
                "description": "Tracking für diesen Termin wurde deaktiviert",
            },
        )
        event.updated_at = datetime.utcnow()
        db.add(event)
        db.commit()
        logger.info("Tracking für Termin %s wurde deaktiviert", event.uid)
    else:
        db.commit()

    db.refresh(event)
    setattr(event, "conflicts", [])
    _attach_sync_state([event])
    return event


@app.post("/events/schedule")
def schedule_sync(minutes: int = 5, db: Session = Depends(get_db)) -> SyncJobStatus:
    def job():
        with SessionLocal() as job_db:
            scan_mailboxes(job_db)

    scheduler.schedule_job(AUTO_SYNC_JOB_ID, job, minutes=minutes)
    return SyncJobStatus(job_id=AUTO_SYNC_JOB_ID, status="scheduled", total=minutes)


def perform_sync_all(
    db: Session,
    apply_auto_response: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Synchronize all pending events based on the configured mappings."""
    total_uploaded = 0
    mappings = db.execute(select(SyncMapping)).scalars().all()
    for mapping in mappings:
        caldav_account = db.get(Account, mapping.caldav_account_id)
        if caldav_account is None:
            logger.warning("CalDAV account %s not found", mapping.caldav_account_id)
            continue
        settings = CalDavSettings(**caldav_account.settings)
        events = db.execute(
            select(TrackedEvent)
            .where(TrackedEvent.source_account_id == mapping.imap_account_id)
            .where(TrackedEvent.source_folder == mapping.imap_folder)
            .where(
                or_(
                    TrackedEvent.status.in_([EventStatus.NEW, EventStatus.UPDATED]),
                    and_(
                        TrackedEvent.status == EventStatus.CANCELLED,
                        or_(
                            TrackedEvent.cancelled_by_organizer.is_(None),
                            TrackedEvent.cancelled_by_organizer.is_(True),
                        ),
                    ),
                )
            )
            .where(TrackedEvent.sync_conflict.is_(False))
            .where(TrackedEvent.tracking_disabled.is_(False))
        ).scalars().all()
        if not events:
            continue
        if progress_callback is not None:
            progress_callback(0, len(events))
        uploaded_uids = event_processor.sync_events_to_calendar(
            events,
            mapping.calendar_url,
            settings,
            progress_callback=(
                (lambda event, success: progress_callback(1, 0))
                if progress_callback is not None
                else None
            ),
        )
        total_uploaded += len(uploaded_uids)
        if (
            apply_auto_response
            and auto_sync_preferences.get("auto_response") == EventResponseStatus.ACCEPTED
            and uploaded_uids
        ):
            accepted_events: List[TrackedEvent] = []
            for event in events:
                if event.uid not in uploaded_uids:
                    continue
                current = db.get(TrackedEvent, event.id)
                if current is None:
                    continue
                current.response_status = EventResponseStatus.ACCEPTED
                event_processor.annotate_response(current)
                current.history = merge_histories(
                    current.history or [],
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "action": "response",
                        "description": "Automatisch zugesagt (AutoSync)",
                    },
                )
                db.add(current)
                accepted_events.append(current)
            db.commit()
            if accepted_events:
                try:
                    event_processor.sync_events_to_calendar(
                        accepted_events, mapping.calendar_url, settings
                    )
                except Exception:
                    logger.exception(
                        "Automatische Zusage für Mapping %s konnte nicht zum Kalender synchronisiert werden",
                        mapping.id,
                    )
    return total_uploaded


@app.post("/events/sync-all", response_model=SyncJobStatus)
def sync_all_events(background_tasks: BackgroundTasks) -> SyncJobStatus:
    state = job_tracker.create("sync-all", total=0)
    job_tracker.update(state.job_id, status="running", processed=0, total=0)
    background_tasks.add_task(_execute_sync_all_job, state.job_id)
    return state.to_status()


@app.get("/jobs/{job_id}", response_model=SyncJobStatus)
def get_job_status(job_id: str) -> SyncJobStatus:
    state = job_tracker.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return state.to_status()


@app.get("/events/auto-sync", response_model=AutoSyncStatus)
def auto_sync_status() -> AutoSyncStatus:
    return AutoSyncStatus(
        enabled=scheduler.is_job_active(AUTO_SYNC_JOB_ID),
        interval_minutes=auto_sync_preferences.get("interval_minutes", 5),
        auto_response=auto_sync_preferences.get("auto_response", EventResponseStatus.NONE),
        active_job=_active_auto_sync_job(),
    )


@app.post("/events/auto-sync", response_model=AutoSyncStatus)
def configure_auto_sync(payload: AutoSyncRequest, db: Session = Depends(get_db)) -> AutoSyncStatus:
    def job():
        with _auto_sync_lock:
            if _auto_sync_state.get("job_id"):
                logger.info("Auto sync job already running, skipping invocation")
                return
            state = job_tracker.create(AUTO_SYNC_JOB_ID, total=0)
            _auto_sync_state["job_id"] = state.job_id
        job_tracker.update(
            state.job_id,
            status="running",
            processed=0,
            total=0,
            detail={
                "phase": "Postfach-Scan",
                "description": "AutoSync: Postfächer werden analysiert…",
                "processed": 0,
                "total": 0,
            },
        )

        try:
            with SessionLocal() as job_db:
                scan_state = {"processed": 0, "total": 0}

                def scan_progress(processed_delta: int, total_delta: int) -> None:
                    if total_delta:
                        job_tracker.increment(state.job_id, total_delta=total_delta)
                        scan_state["total"] += total_delta
                    if processed_delta:
                        job_tracker.increment(state.job_id, processed_delta=processed_delta)
                        scan_state["processed"] += processed_delta
                    job_tracker.update(
                        state.job_id,
                        detail={
                            "phase": "Postfach-Scan",
                            "description": "AutoSync: Postfächer werden analysiert…",
                            "processed": scan_state["processed"],
                            "total": scan_state["total"],
                        },
                    )

                messages, events = perform_mail_scan(job_db, progress_callback=scan_progress)

                job_tracker.update(
                    state.job_id,
                    detail={
                        "phase": "Synchronisation",
                        "description": "AutoSync: Kalenderabgleich läuft…",
                        "processed": 0,
                        "total": 0,
                    },
                )

                sync_state = {"processed": 0, "total": 0}

                def sync_progress(processed_delta: int, total_delta: int) -> None:
                    if total_delta:
                        job_tracker.increment(state.job_id, total_delta=total_delta)
                        sync_state["total"] += total_delta
                    if processed_delta:
                        job_tracker.increment(state.job_id, processed_delta=processed_delta)
                        sync_state["processed"] += processed_delta
                    job_tracker.update(
                        state.job_id,
                        detail={
                            "phase": "Synchronisation",
                            "description": "AutoSync: Kalenderabgleich läuft…",
                            "processed": sync_state["processed"],
                            "total": sync_state["total"],
                        },
                    )

                uploaded = perform_sync_all(
                    job_db,
                    apply_auto_response=True,
                    progress_callback=sync_progress,
                )

            job_tracker.finish(
                state.job_id,
                detail={
                    "messages_processed": messages,
                    "events_imported": events,
                    "uploaded": uploaded,
                    "phase": "Synchronisation",
                    "description": "AutoSync abgeschlossen",
                },
            )
        except Exception:
            logger.exception("Auto sync job %s failed", state.job_id)
            job_tracker.fail(state.job_id, "AutoSync fehlgeschlagen.")
        finally:
            with _auto_sync_lock:
                _auto_sync_state["job_id"] = None

    auto_response = payload.auto_response
    if auto_response not in (EventResponseStatus.NONE, EventResponseStatus.ACCEPTED):
        logger.warning("Unsupported auto response %s, falling back to NONE", auto_response)
        auto_response = EventResponseStatus.NONE
    auto_sync_preferences["auto_response"] = auto_response

    # Normalize the interval to stay within reasonable scheduler boundaries.
    interval_minutes = payload.interval_minutes
    if interval_minutes < 1:
        logger.warning("Interval %s is below minimum, normalizing to 1 minute", interval_minutes)
        interval_minutes = 1
    elif interval_minutes > 720:
        logger.warning("Interval %s exceeds maximum, normalizing to 720 minutes", interval_minutes)
        interval_minutes = 720

    previous_interval = auto_sync_preferences.get("interval_minutes")
    if previous_interval != interval_minutes:
        logger.info("Updating auto sync interval from %s to %s minutes", previous_interval, interval_minutes)

    auto_sync_preferences["interval_minutes"] = interval_minutes

    if payload.enabled:
        scheduler.schedule_job(AUTO_SYNC_JOB_ID, job, minutes=interval_minutes)
        logger.info("Auto sync enabled")
    else:
        scheduler.cancel_job(AUTO_SYNC_JOB_ID)
        logger.info("Auto sync disabled")
    return AutoSyncStatus(
        enabled=scheduler.is_job_active(AUTO_SYNC_JOB_ID),
        interval_minutes=auto_sync_preferences.get("interval_minutes", 5),
        auto_response=auto_sync_preferences.get("auto_response", EventResponseStatus.NONE),
        active_job=_active_auto_sync_job(),
    )


@app.get("/accounts/{account_id}/calendars")
def get_calendars(account_id: int, db: Session = Depends(get_db)) -> dict[str, List[dict[str, str]]]:
    account = db.get(Account, account_id)
    if account is None or account.type != AccountType.CALDAV:
        raise HTTPException(status_code=404, detail="CalDAV account not found")
    settings = CalDavSettings(**account.settings)
    calendars = list(list_calendars(settings))
    return {"calendars": calendars}


@app.get("/sync-mappings", response_model=List[SyncMappingRead])
def list_mappings(db: Session = Depends(get_db)) -> List[SyncMapping]:
    return db.execute(select(SyncMapping)).scalars().all()


@app.post("/sync-mappings", response_model=SyncMappingRead)
def create_mapping(payload: SyncMappingCreate, db: Session = Depends(get_db)) -> SyncMapping:
    imap_account = db.get(Account, payload.imap_account_id)
    caldav_account = db.get(Account, payload.caldav_account_id)
    if imap_account is None or imap_account.type != AccountType.IMAP:
        raise HTTPException(status_code=400, detail="Ungültiges IMAP Konto")
    if caldav_account is None or caldav_account.type != AccountType.CALDAV:
        raise HTTPException(status_code=400, detail="Ungültiges CalDAV Konto")
    mapping = SyncMapping(
        imap_account_id=payload.imap_account_id,
        imap_folder=payload.imap_folder,
        caldav_account_id=payload.caldav_account_id,
        calendar_url=str(payload.calendar_url),
        calendar_name=payload.calendar_name,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


@app.put("/sync-mappings/{mapping_id}", response_model=SyncMappingRead)
def update_mapping(mapping_id: int, payload: SyncMappingUpdate, db: Session = Depends(get_db)) -> SyncMapping:
    mapping = db.get(SyncMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping nicht gefunden")
    if payload.calendar_url is not None:
        mapping.calendar_url = str(payload.calendar_url)
    if payload.calendar_name is not None:
        mapping.calendar_name = payload.calendar_name
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


@app.delete("/sync-mappings/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    mapping = db.get(SyncMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping nicht gefunden")
    db.delete(mapping)
    db.commit()
    return {"deleted": True}
