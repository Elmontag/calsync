"""FastAPI application for CalSync."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import (
    Account,
    AccountType,
    EventStatus,
    ImapFolder,
    SyncDirection,
    SyncMapping,
    TrackedEvent,
)
from .schemas import (
    AccountCreate,
    AccountRead,
    ConnectionTestRequest,
    ConnectionTestResult,
    ManualSyncRequest,
    AutoSyncRequest,
    AutoSyncStatus,
    SyncJobStatus,
    SyncMappingCreate,
    SyncMappingRead,
    SyncMappingUpdate,
    TrackedEventRead,
)
from .services import event_processor
from .services.caldav_client import CalDavSettings, list_calendars
from .services.imap_client import ImapSettings, fetch_calendar_candidates
from .services.scheduler import scheduler
from .utils.ics_parser import parse_ics_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CalSync", version="0.1.0")

AUTO_SYNC_JOB_ID = "auto-sync"

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
        direction=account.direction,
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


@app.post("/events/manual-sync")
def manual_sync(payload: ManualSyncRequest) -> dict[str, List[str]]:
    settings = CalDavSettings(
        url=str(payload.target_calendar),
    )
    uploaded = event_processor.manual_sync(payload, settings)
    return {"uploaded": uploaded}


@app.post("/events/schedule")
def schedule_sync(minutes: int = 5, db: Session = Depends(get_db)) -> SyncJobStatus:
    def job():
        with SessionLocal() as job_db:
            scan_mailboxes(job_db)

    scheduler.schedule_job(AUTO_SYNC_JOB_ID, job, minutes=minutes)
    return SyncJobStatus(job_id=AUTO_SYNC_JOB_ID, status="scheduled", total=minutes)


def perform_sync_all(db: Session) -> int:
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
        uploaded = event_processor.sync_events_to_calendar(events, mapping.calendar_url, settings)
        total_uploaded += len(uploaded)
    return total_uploaded


@app.post("/events/sync-all", response_model=SyncJobStatus)
def sync_all_events(db: Session = Depends(get_db)) -> SyncJobStatus:
    processed = perform_sync_all(db)
    return SyncJobStatus(job_id="manual-sync-all", status="completed", processed=processed)


@app.get("/events/auto-sync", response_model=AutoSyncStatus)
def auto_sync_status() -> AutoSyncStatus:
    return AutoSyncStatus(enabled=scheduler.is_job_active(AUTO_SYNC_JOB_ID))


@app.post("/events/auto-sync", response_model=AutoSyncStatus)
def configure_auto_sync(payload: AutoSyncRequest, db: Session = Depends(get_db)) -> AutoSyncStatus:
    def job():
        with SessionLocal() as job_db:
            scan_mailboxes(job_db)
            perform_sync_all(job_db)

    if payload.enabled:
        scheduler.schedule_job(AUTO_SYNC_JOB_ID, job, minutes=payload.interval_minutes)
        logger.info("Auto sync enabled")
    else:
        scheduler.cancel_job(AUTO_SYNC_JOB_ID)
        logger.info("Auto sync disabled")
    return AutoSyncStatus(enabled=scheduler.is_job_active(AUTO_SYNC_JOB_ID), interval_minutes=payload.interval_minutes)


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
