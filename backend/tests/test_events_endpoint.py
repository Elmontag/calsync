"""Regression tests for the /events endpoint helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover - test bootstrap code
    sys.path.insert(0, str(ROOT))

from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app, list_events, perform_sync_all
from backend.app.models import (
    Account,
    AccountType,
    EventResponseStatus,
    EventStatus,
    SyncMapping,
    TrackedEvent,
)
from backend.app.services import event_processor
from backend.app.services.caldav_client import CalDavSettings
from sqlalchemy import select


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


def _store_event(
    session: SessionLocal,
    *,
    uid: str,
    account: Account,
    folder: str,
    start: Optional[datetime] = None,
) -> None:
    now = start or datetime.now(tz=timezone.utc)
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
    inbox_start = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    team_start = inbox_start + timedelta(days=1)
    _store_event(session, uid="uid-1", account=imap, folder="INBOX", start=inbox_start)
    _store_event(session, uid="uid-2", account=imap, folder="Team", start=team_start)

    monkeypatch.setattr("backend.app.main.CalDavConnection", lambda settings: _FakeConnection())

    calls: List[Tuple[datetime, datetime, Optional[str]]] = []

    def _conflicts(
        _calendar: Any,
        start: datetime,
        end: datetime,
        exclude_uid: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        calls.append((start, end, exclude_uid))
        if abs((start - inbox_start).total_seconds()) < 1:
            return [
                {
                    "uid": "conflict-uid",
                    "summary": "Überschneidung",
                    "start": inbox_start.isoformat(),
                    "end": (inbox_start + timedelta(hours=1)).isoformat(),
                }
            ]
        return []

    monkeypatch.setattr("backend.app.main.find_conflicting_events", _conflicts)

    events = list_events(db=session)

    assert {event.uid for event in events} == {"uid-1", "uid-2"}
    mapped = {event.uid: getattr(event, "conflicts", []) for event in events}
    assert mapped["uid-1"][0]["uid"] == "conflict-uid"
    assert mapped["uid-2"] == []
    assert len(calls) == 2


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


def test_conflict_lookup_runs_once_per_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conflict detection fetches CalDAV data only once per mapping regardless of event count."""

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

    primary_start = datetime(2024, 2, 1, 10, 0, tzinfo=timezone.utc)
    later_start = primary_start + timedelta(hours=4)
    _store_event(session, uid="uid-a", account=imap, folder="INBOX", start=primary_start)
    _store_event(session, uid="uid-b", account=imap, folder="INBOX", start=later_start)

    monkeypatch.setattr("backend.app.main.CalDavConnection", lambda settings: _FakeConnection())

    call_count = 0

    def _conflicts(
        _calendar: Any,
        start: datetime,
        end: datetime,
        exclude_uid: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        assert exclude_uid is None
        assert start <= primary_start <= end
        return [
            {
                "uid": "conflict-shared",
                "summary": "Paralleltermin",
                "start": primary_start.isoformat(),
                "end": (primary_start + timedelta(hours=1)).isoformat(),
            }
        ]

    monkeypatch.setattr("backend.app.main.find_conflicting_events", _conflicts)

    events = list_events(db=session)

    conflicts_by_uid = {event.uid: getattr(event, "conflicts", []) for event in events}
    assert conflicts_by_uid["uid-a"][0]["uid"] == "conflict-shared"
    assert conflicts_by_uid["uid-b"] == []
    assert call_count == 1


def test_events_endpoint_handles_multiple_folders_with_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API returns all events when conflict detection runs across multiple folders."""

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
                calendar_url="https://cal.example.com/team",
            ),
        ]
    )
    session.commit()

    inbox_start = datetime(2024, 3, 1, 8, 0, tzinfo=timezone.utc)
    team_start = inbox_start + timedelta(days=1)
    _store_event(session, uid="uid-1", account=imap, folder="INBOX", start=inbox_start)
    _store_event(session, uid="uid-2", account=imap, folder="Team", start=team_start)

    # Force legacy payload cleanup during the request to reproduce the regression conditions.
    legacy_event = session.execute(
        select(TrackedEvent).where(TrackedEvent.uid == "uid-1")
    ).scalar_one()
    legacy_event.history = json.dumps({"broken": True})
    session.commit()
    session.close()

    calls: List[Tuple[datetime, datetime, Optional[str]]] = []

    def _conflicts(
        _calendar: Any,
        start: datetime,
        end: datetime,
        exclude_uid: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        calls.append((start, end, exclude_uid))
        if abs((start - inbox_start).total_seconds()) < 1:
            return [
                {
                    "uid": "conflict-1",
                    "summary": "Überschneidung",
                    "start": inbox_start.isoformat(),
                    "end": (inbox_start + timedelta(hours=1)).isoformat(),
                }
            ]
        return []

    monkeypatch.setattr("backend.app.main.CalDavConnection", lambda settings: _FakeConnection())
    monkeypatch.setattr("backend.app.main.find_conflicting_events", _conflicts)

    client = TestClient(app)
    response = client.get("/events")

    assert response.status_code == 200
    payload = response.json()
    assert {event["uid"] for event in payload} == {"uid-1", "uid-2"}
    mapped = {event["uid"]: event for event in payload}
    assert mapped["uid-1"]["conflicts"][0]["uid"] == "conflict-1"
    assert mapped["uid-2"]["conflicts"] == []
    assert len(calls) == 2


def test_perform_sync_all_filters_attendee_cancellations(monkeypatch: pytest.MonkeyPatch) -> None:
    """AutoSync skips attendee cancellations while keeping organizer cancellations."""

    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    mapping = SyncMapping(
        imap_account_id=imap.id,
        imap_folder="INBOX",
        caldav_account_id=caldav.id,
        calendar_url="https://cal.example.com/shared",
    )
    session.add(mapping)

    base_kwargs = dict(
        source_account_id=imap.id,
        source_folder="INBOX",
        start=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        response_status=EventResponseStatus.NONE,
        payload="BEGIN:VEVENT\nUID:test\nEND:VEVENT",
        history=[],
    )
    session.add_all(
        [
            TrackedEvent(uid="uid-new", status=EventStatus.NEW, **base_kwargs),
            TrackedEvent(
                uid="uid-cancel-organizer",
                status=EventStatus.CANCELLED,
                cancelled_by_organizer=True,
                **base_kwargs,
            ),
            TrackedEvent(
                uid="uid-cancel-attendee",
                status=EventStatus.CANCELLED,
                cancelled_by_organizer=False,
                **base_kwargs,
            ),
            TrackedEvent(
                uid="uid-cancel-legacy",
                status=EventStatus.CANCELLED,
                **base_kwargs,
            ),
        ]
    )
    session.commit()

    captured: List[List[str]] = []

    def _fake_sync(events, calendar_url, settings, progress_callback=None):
        captured.append([event.uid for event in events])
        if progress_callback is not None:
            for event in events:
                progress_callback(event, True)
        return [event.uid for event in events if event.status != EventStatus.CANCELLED]

    monkeypatch.setattr(event_processor, "sync_events_to_calendar", _fake_sync)

    uploaded = perform_sync_all(session)

    flattened = {uid for batch in captured for uid in batch}
    assert "uid-new" in flattened
    assert "uid-cancel-organizer" in flattened
    assert "uid-cancel-legacy" in flattened
    assert "uid-cancel-attendee" not in flattened
    assert uploaded == 1


def test_attendee_cancellation_updates_history_without_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellations from attendees must not trigger deletions but still leave a history entry."""

    session = SessionLocal()
    imap, _caldav = _store_basic_accounts(session)
    event = TrackedEvent(
        uid="uid-attendee",
        status=EventStatus.CANCELLED,
        response_status=EventResponseStatus.NONE,
        source_account_id=imap.id,
        source_folder="INBOX",
        start=datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc),
        end=datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
        cancelled_by_organizer=False,
        payload="BEGIN:VEVENT\nUID:uid-attendee\nEND:VEVENT",
        history=[],
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    delete_calls: List[str] = []

    def _fake_delete(calendar_url: str, uid: str, settings) -> bool:  # pragma: no cover - verification helper
        delete_calls.append(uid)
        return True

    monkeypatch.setattr(event_processor, "delete_event_by_uid", _fake_delete)

    settings = CalDavSettings(url="https://cal.example.com", username="user", password="secret")
    result = event_processor.sync_events_to_calendar([event], "https://cal.example.com/shared", settings)

    assert result == []
    assert delete_calls == []

    session.refresh(event)
    assert event.last_synced is not None
    assert any(
        entry.get("description") == "Absage ignoriert (nicht vom Ersteller)"
        for entry in event.history or []
    )
