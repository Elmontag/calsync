"""Pydantic schemas for API requests and responses."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import AccountType, EventResponseStatus, EventStatus


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
    settings: dict[str, Any]
    imap_folders: List[ImapFolderCreate] = Field(default_factory=list)


class AccountCreate(AccountBase):
    pass


class AccountUpdate(AccountBase):
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


class CalendarConflict(BaseModel):
    uid: str
    summary: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None


class TrackedEventRead(BaseModel):
    id: int
    uid: str
    source_account_id: Optional[int] = None
    source_folder: Optional[str] = None
    summary: Optional[str] = None
    organizer: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    status: EventStatus
    response_status: EventResponseStatus
    history: List[EventHistoryEntry] = Field(default_factory=list)
    conflicts: List[CalendarConflict] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ManualSyncRequest(BaseModel):
    event_ids: List[int]


class EventResponseUpdate(BaseModel):
    response: EventResponseStatus


class ManualSyncMissingDetail(BaseModel):
    event_id: int
    uid: Optional[str] = None
    account_id: Optional[int] = None
    folder: Optional[str] = None
    reason: str


class ManualSyncResponse(BaseModel):
    uploaded: List[str] = Field(default_factory=list)
    missing: List[ManualSyncMissingDetail] = Field(default_factory=list)


class SyncJobStatus(BaseModel):
    job_id: str
    status: str
    processed: int = 0
    total: Optional[int] = None
    detail: Optional[dict[str, Any]] = None
    message: Optional[str] = None


class SyncMappingBase(BaseModel):
    imap_account_id: int
    imap_folder: str
    caldav_account_id: int
    calendar_url: HttpUrl
    calendar_name: Optional[str] = None


class SyncMappingCreate(SyncMappingBase):
    pass


class SyncMappingUpdate(BaseModel):
    calendar_url: Optional[HttpUrl] = None
    calendar_name: Optional[str] = None


class SyncMappingRead(SyncMappingBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class AutoSyncStatus(BaseModel):
    enabled: bool
    interval_minutes: Optional[int] = None
    auto_response: EventResponseStatus = EventResponseStatus.NONE


class AutoSyncRequest(BaseModel):
    enabled: bool
    interval_minutes: int = Field(default=5, ge=1, le=720)
    auto_response: EventResponseStatus = EventResponseStatus.NONE
