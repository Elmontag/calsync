"""SQLAlchemy models for CalSync."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class AccountType(str, Enum):
    """Different account types used for synchronization."""

    IMAP = "imap"
    CALDAV = "caldav"


class Account(Base):
    """Database representation of a configured account."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)
    type = Column(SqlEnum(AccountType), nullable=False)
    settings = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    imap_folders = relationship("ImapFolder", back_populates="account", cascade="all, delete-orphan")


class ImapFolder(Base):
    """List of IMAP folders that should be scanned."""

    __tablename__ = "imap_folders"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    name = Column(String, nullable=False)
    include_subfolders = Column(Boolean, default=True)

    account = relationship("Account", back_populates="imap_folders")


class EventStatus(str, Enum):
    """Internal state for tracked events."""

    NEW = "new"
    UPDATED = "updated"
    CANCELLED = "cancelled"
    SYNCED = "synced"
    FAILED = "failed"


class EventResponseStatus(str, Enum):
    """Possible participation responses for a tracked event."""

    NONE = "none"
    ACCEPTED = "accepted"
    TENTATIVE = "tentative"
    DECLINED = "declined"


class TrackedEvent(Base):
    """State of events extracted from IMAP sources."""

    __tablename__ = "tracked_events"

    id = Column(Integer, primary_key=True, index=True)
    uid = Column(String, unique=True, nullable=False)
    mailbox_message_id = Column(String, nullable=True)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    source_folder = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    organizer = Column(String, nullable=True)
    start = Column(DateTime, nullable=True)
    end = Column(DateTime, nullable=True)
    status = Column(SqlEnum(EventStatus), default=EventStatus.NEW)
    response_status = Column(
        SqlEnum(
            EventResponseStatus,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            validate_strings=True,
        ),
        # SQLite stores Enum values as strings; using the value list keeps
        # existing lower-case payloads readable while still mapping to the
        # Enum instances in Python.
        default=EventResponseStatus.NONE,
        nullable=False,
    )
    cancelled_by_organizer = Column(Boolean, nullable=True)
    payload = Column(JSON, nullable=True)
    last_synced = Column(DateTime, nullable=True)
    history = Column(JSON, default=list)
    caldav_etag = Column(String, nullable=True)
    local_version = Column(Integer, default=0, nullable=False)
    synced_version = Column(Integer, default=0, nullable=False)
    remote_last_modified = Column(DateTime, nullable=True)
    local_last_modified = Column(DateTime, nullable=True)
    last_modified_source = Column(String, nullable=True)
    sync_conflict = Column(Boolean, default=False, nullable=False)
    sync_conflict_reason = Column(Text, nullable=True)
    sync_conflict_snapshot = Column(JSON, nullable=True)
    tracking_disabled = Column(Boolean, default=False, nullable=False)
    mail_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ignored_mail_imports = relationship(
        "IgnoredMailImport", back_populates="event", cascade="all, delete-orphan"
    )


class IgnoredMailImport(Base):
    """Persist markers for mail messages that should no longer update an event."""

    __tablename__ = "ignored_mail_imports"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("tracked_events.id"), nullable=False)
    account_id = Column(Integer, nullable=True)
    folder = Column(String, nullable=True)
    message_id = Column(String, nullable=False)
    max_uid = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    event = relationship("TrackedEvent", back_populates="ignored_mail_imports")


class SyncMapping(Base):
    """Configuration describing how IMAP sources map to CalDAV targets."""

    __tablename__ = "sync_mappings"

    id = Column(Integer, primary_key=True, index=True)
    imap_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    imap_folder = Column(String, nullable=False)
    caldav_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    calendar_url = Column(String, nullable=False)
    calendar_name = Column(String, nullable=True)

    imap_account = relationship("Account", foreign_keys=[imap_account_id])
    caldav_account = relationship("Account", foreign_keys=[caldav_account_id])
