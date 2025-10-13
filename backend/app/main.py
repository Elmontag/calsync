"""FastAPI application for CalSync."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
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
    ManualSyncMissingDetail,
    ManualSyncRequest,
    ManualSyncResponse,
    EventResponseUpdate,
    AutoSyncRequest,
    AutoSyncStatus,
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
from .services.imap_client import ImapSettings, fetch_calendar_candidates
from .services.scheduler import scheduler
from .utils.ics_parser import merge_histories, parse_ics_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CalSync", version="0.1.0")

AUTO_SYNC_JOB_ID = "auto-sync"
auto_sync_preferences: Dict[str, Any] = {
    "auto_response": EventResponseStatus.NONE,
    "interval_minutes": 5,
}


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
                for event in events_for_mapping:
                    start, end = _event_search_window(event)
                    if start is None or end is None:
                        continue
                    conflicts = find_conflicting_events(
                        calendar, start, end, exclude_uid=event.uid
                    )
                    if conflicts:
                        setattr(event, "conflicts", conflicts)
        except Exception:
            logger.exception(
                "Konfliktprüfung für Mapping %s fehlgeschlagen", mapping.id
            )
            continue
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
    events = db.execute(select(TrackedEvent)).scalars().all()
    _attach_conflicts(events, db)
    return events


@app.post("/events/scan", response_model=SyncJobStatus)
def scan_mailboxes(db: Session = Depends(get_db)):
    accounts = db.execute(select(Account).where(Account.type == AccountType.IMAP)).scalars().all()
    total_processed = 0
    for account in accounts:
        folders = [folder.name for folder in account.imap_folders] or ["INBOX"]
        settings = ImapSettings(**account.settings)
        candidates = fetch_calendar_candidates(settings, folders)
        for candidate in candidates:
            for attachment in candidate.attachments:
                parsed_events = parse_ics_payload(attachment.payload)
                stored = event_processor.upsert_events(
                    parsed_events,
                    candidate.message_id,
                    source_account_id=account.id,
                    source_folder=candidate.folder,
                )
                total_processed += len(stored)
    return SyncJobStatus(job_id="manual-scan", status="completed", processed=total_processed)


@app.post("/events/manual-sync", response_model=ManualSyncResponse)
def manual_sync(payload: ManualSyncRequest, db: Session = Depends(get_db)) -> ManualSyncResponse:
    if not payload.event_ids:
        return ManualSyncResponse(uploaded=[])

    events = (
        db.execute(select(TrackedEvent).where(TrackedEvent.id.in_(payload.event_ids)))
        .scalars()
        .all()
    )
    if not events:
        raise HTTPException(status_code=404, detail="Keine passenden Termine gefunden")

    missing_events: list[ManualSyncMissingDetail] = []
    sync_groups: Dict[int, Dict[str, Any]] = {}

    for event in events:
        if event.source_account_id is None or not event.source_folder:
            missing_events.append(
                ManualSyncMissingDetail(
                    event_id=event.id,
                    uid=event.uid,
                    reason="Keine Quellinformationen vorhanden",
                )
            )
            continue

        mapping = (
            db.execute(
                select(SyncMapping)
                .where(SyncMapping.imap_account_id == event.source_account_id)
                .where(SyncMapping.imap_folder == event.source_folder)
            )
            .scalars()
            .first()
        )
        if mapping is None:
            missing_events.append(
                ManualSyncMissingDetail(
                    event_id=event.id,
                    uid=event.uid,
                    account_id=event.source_account_id,
                    folder=event.source_folder,
                    reason="Keine Sync-Zuordnung für Konto und Ordner",
                )
            )
            continue

        caldav_account = db.get(Account, mapping.caldav_account_id)
        if caldav_account is None or caldav_account.type != AccountType.CALDAV:
            missing_events.append(
                ManualSyncMissingDetail(
                    event_id=event.id,
                    uid=event.uid,
                    account_id=event.source_account_id,
                    folder=event.source_folder,
                    reason="Zugeordnetes CalDAV-Konto nicht gefunden",
                )
            )
            continue

        try:
            settings = CalDavSettings(**caldav_account.settings)
        except TypeError as exc:
            logger.exception("CalDAV settings invalid for account %s", caldav_account.id)
            missing_events.append(
                ManualSyncMissingDetail(
                    event_id=event.id,
                    uid=event.uid,
                    account_id=event.source_account_id,
                    folder=event.source_folder,
                    reason=f"Ungültige CalDAV Einstellungen: {exc}",
                )
            )
            continue

        group = sync_groups.setdefault(
            mapping.id,
            {"events": [], "mapping": mapping, "settings": settings},
        )
        group["events"].append(event)

    if missing_events:
        logger.warning("Manual sync completed with missing mappings: %s", missing_events)

    uploaded: list[str] = []
    for group in sync_groups.values():
        mapping: SyncMapping = group["mapping"]
        settings: CalDavSettings = group["settings"]
        events_for_mapping: List[TrackedEvent] = group["events"]
        uploaded.extend(
            event_processor.sync_events_to_calendar(
                events_for_mapping,
                mapping.calendar_url,
                settings,
            )
        )

    return ManualSyncResponse(uploaded=uploaded, missing=missing_events)


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
    return event


@app.post("/events/schedule")
def schedule_sync(minutes: int = 5, db: Session = Depends(get_db)) -> SyncJobStatus:
    def job():
        with SessionLocal() as job_db:
            scan_mailboxes(job_db)

    scheduler.schedule_job(AUTO_SYNC_JOB_ID, job, minutes=minutes)
    return SyncJobStatus(job_id=AUTO_SYNC_JOB_ID, status="scheduled", total=minutes)


def perform_sync_all(db: Session, apply_auto_response: bool = False) -> int:
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
            .where(TrackedEvent.status != EventStatus.SYNCED)
        ).scalars().all()
        if not events:
            continue
        uploaded_uids = event_processor.sync_events_to_calendar(
            events, mapping.calendar_url, settings
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
def sync_all_events(db: Session = Depends(get_db)) -> SyncJobStatus:
    processed = perform_sync_all(db)
    return SyncJobStatus(job_id="manual-sync-all", status="completed", processed=processed)


@app.get("/events/auto-sync", response_model=AutoSyncStatus)
def auto_sync_status() -> AutoSyncStatus:
    return AutoSyncStatus(
        enabled=scheduler.is_job_active(AUTO_SYNC_JOB_ID),
        interval_minutes=auto_sync_preferences.get("interval_minutes"),
        auto_response=auto_sync_preferences.get("auto_response", EventResponseStatus.NONE),
    )


@app.post("/events/auto-sync", response_model=AutoSyncStatus)
def configure_auto_sync(payload: AutoSyncRequest, db: Session = Depends(get_db)) -> AutoSyncStatus:
    def job():
        with SessionLocal() as job_db:
            scan_mailboxes(job_db)
            perform_sync_all(job_db, apply_auto_response=True)

    auto_response = payload.auto_response
    if auto_response not in (EventResponseStatus.NONE, EventResponseStatus.ACCEPTED):
        logger.warning("Unsupported auto response %s, falling back to NONE", auto_response)
        auto_response = EventResponseStatus.NONE
    auto_sync_preferences["auto_response"] = auto_response
    auto_sync_preferences["interval_minutes"] = payload.interval_minutes

    if payload.enabled:
        scheduler.schedule_job(AUTO_SYNC_JOB_ID, job, minutes=payload.interval_minutes)
        logger.info("Auto sync enabled")
    else:
        scheduler.cancel_job(AUTO_SYNC_JOB_ID)
        logger.info("Auto sync disabled")
    return AutoSyncStatus(
        enabled=scheduler.is_job_active(AUTO_SYNC_JOB_ID),
        interval_minutes=auto_sync_preferences.get("interval_minutes"),
        auto_response=auto_sync_preferences.get("auto_response", EventResponseStatus.NONE),
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
