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
from .models import Account, AccountType, ImapFolder, SyncDirection, TrackedEvent
from .schemas import (
    AccountCreate,
    AccountRead,
    ConnectionTestRequest,
    ConnectionTestResult,
    ManualSyncRequest,
    SyncJobStatus,
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
                stored = event_processor.upsert_events(parsed_events, candidate.message_id)
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

    scheduler.schedule_job("auto-sync", job, minutes=minutes)
    return SyncJobStatus(job_id="auto-sync", status="scheduled", total=minutes)
