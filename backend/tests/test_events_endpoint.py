"""Regression tests for the /events endpoint helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover - test bootstrap code
    sys.path.insert(0, str(ROOT))

from backend.app.database import Base, SessionLocal, engine
from backend.app.main import list_events
from backend.app.models import (
    Account,
    AccountType,
    EventResponseStatus,
    EventStatus,
    SyncMapping,
    TrackedEvent,
)


@pytest.fixture(autouse=True)
def reset_database() -> Iterator[None]:
    """Provide a clean SQLite file for every test run."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)


class _FakeCalendar:
    def date_search(self, start: datetime, end: datetime):  # pragma: no cover - return empty iterator
        return []


class _FakePrincipal:
    def calendar(self, cal_url: str):  # pragma: no cover - trivial proxy
        return _FakeCalendar()


class _FakeConnection:
    def principal(self) -> _FakePrincipal:  # pragma: no cover - trivial proxy
        return _FakePrincipal()

    def __enter__(self) -> "_FakeConnection":  # pragma: no cover - trivial proxy
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - nothing to clean up
        return None


def _store_basic_accounts(session: SessionLocal) -> tuple[Account, Account]:
    imap = Account(
        label="IMAP",
        type=AccountType.IMAP,
        settings={"host": "imap.example.com"},
    )
    caldav = Account(
        label="CalDAV",
        type=AccountType.CALDAV,
        settings={"url": "https://cal.example.com", "username": "user", "password": "secret"},
    )
    session.add_all([imap, caldav])
    session.commit()
    session.refresh(imap)
    session.refresh(caldav)
    return imap, caldav


def _store_event(session: SessionLocal, *, uid: str, account: Account, folder: str) -> None:
    now = datetime.now(tz=timezone.utc)
    session.add(
        TrackedEvent(
            uid=uid,
            summary=f"Event {uid}",
            start=now,
            end=now + timedelta(hours=1),
            status=EventStatus.NEW,
            response_status=EventResponseStatus.NONE,
            source_account_id=account.id,
            source_folder=folder,
            history=[],
        )
    )
    session.commit()


def test_list_events_handles_duplicate_caldav_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Listing events remains stable when different folders target the same calendar."""
    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    session.add_all(
        [
            SyncMapping(
                imap_account_id=imap.id,
                imap_folder="INBOX",
                caldav_account_id=caldav.id,
                calendar_url="https://cal.example.com/shared",
            ),
            SyncMapping(
                imap_account_id=imap.id,
                imap_folder="Team",
                caldav_account_id=caldav.id,
                calendar_url="https://cal.example.com/shared",
            ),
        ]
    )
    session.commit()
    _store_event(session, uid="uid-1", account=imap, folder="INBOX")
    _store_event(session, uid="uid-2", account=imap, folder="Team")

    monkeypatch.setattr("backend.app.main.CalDavConnection", lambda settings: _FakeConnection())

    events = list_events(db=session)

    assert {event.uid for event in events} == {"uid-1", "uid-2"}
    for event in events:
        assert getattr(event, "conflicts", []) == []


class _ExplodingConnection:
    def __enter__(self) -> "_ExplodingConnection":
        raise RuntimeError("CalDAV offline")

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - unreachable
        return None


def test_list_events_survives_conflict_lookup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network errors during conflict detection must not prevent returning events."""
    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    session.add(
        SyncMapping(
            imap_account_id=imap.id,
            imap_folder="INBOX",
            caldav_account_id=caldav.id,
            calendar_url="https://cal.example.com/shared",
        )
    )
    session.commit()
    _store_event(session, uid="uid-err", account=imap, folder="INBOX")

    monkeypatch.setattr("backend.app.main.CalDavConnection", lambda settings: _ExplodingConnection())

    events = list_events(db=session)

    assert [event.uid for event in events] == ["uid-err"]
    assert getattr(events[0], "conflicts", []) == []
