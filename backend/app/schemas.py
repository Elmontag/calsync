"""Pydantic schemas for API requests and responses."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import AccountType, EventStatus, SyncDirection


class ImapFolderBase(BaseModel):
    name: str
    include_subfolders: bool = True


class ImapFolderCreate(ImapFolderBase):
    pass


class ImapFolderRead(ImapFolderBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class AccountBase(BaseModel):
    label: str
    type: AccountType
    direction: SyncDirection = SyncDirection.IMAP_TO_CALDAV
    settings: dict[str, Any]
    imap_folders: List[ImapFolderCreate] = Field(default_factory=list)


class AccountCreate(AccountBase):
    pass


class AccountRead(AccountBase):
    id: int

    imap_folders: List[ImapFolderRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConnectionTestRequest(BaseModel):
    type: AccountType
    settings: dict[str, Any]


class ConnectionTestResult(BaseModel):
    success: bool
    message: str
    details: Optional[dict[str, Any]] = None


class EventHistoryEntry(BaseModel):
    timestamp: datetime
    action: str
    description: str


class TrackedEventRead(BaseModel):
    id: int
    uid: str
    summary: Optional[str] = None
    organizer: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    status: EventStatus
    history: List[EventHistoryEntry] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ManualSyncRequest(BaseModel):
    event_ids: List[int]
    target_calendar: HttpUrl


class SyncJobStatus(BaseModel):
    job_id: str
    status: str
    processed: int = 0
    total: Optional[int] = None
