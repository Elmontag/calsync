"""Regression tests for the /events endpoint helpers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from textwrap import dedent
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover - test bootstrap code
    sys.path.insert(0, str(ROOT))

from backend.app.database import Base, SessionLocal, engine, session_scope
from backend.app.main import app, list_events, perform_sync_all, _execute_manual_sync_job
from backend.app.models import (
    Account,
    AccountType,
    EventResponseStatus,
    EventStatus,
    SyncMapping,
    TrackedEvent,
)
from backend.app.services import event_processor
from backend.app.services.caldav_client import CalDavSettings, RemoteEventState
from backend.app.services.job_tracker import job_tracker
from backend.app.utils.ics_parser import parse_ics_payload
from sqlalchemy import select
from icalendar import Calendar, Event as ICalEvent


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


def _build_ical(
    *,
    method: Optional[str],
    uid: str,
    summary: str,
    start: datetime,
    end: datetime,
    status: str,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    calendar = Calendar()
    calendar.add("PRODID", "-//CalSync Tests//DE")
    calendar.add("VERSION", "2.0")
    if method:
        calendar.add("METHOD", method)
    component = ICalEvent()
    component.add("UID", uid)
    component.add("SUMMARY", summary)
    component.add("DTSTART", start)
    component.add("DTEND", end)
    component.add("DTSTAMP", start)
    component.add("LAST-MODIFIED", end)
    component.add("STATUS", status)
    if description:
        component.add("DESCRIPTION", description)
    if location:
        component.add("LOCATION", location)
    calendar.add_component(component)
    return calendar.to_ical().decode()


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


def test_perform_sync_all_ignores_sync_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events mit Synchronisationskonflikten dürfen nicht erneut exportiert werden."""

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
        start=datetime(2024, 2, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2024, 2, 1, 10, 0, tzinfo=timezone.utc),
        response_status=EventResponseStatus.NONE,
        payload="BEGIN:VEVENT\nUID:test\nEND:VEVENT",
        history=[],
    )

    session.add_all(
        [
            TrackedEvent(
                uid="uid-conflict",
                status=EventStatus.UPDATED,
                sync_conflict=True,
                sync_conflict_reason="Remote-Version abweichend",
                **base_kwargs,
            ),
            TrackedEvent(
                uid="uid-pending",
                status=EventStatus.UPDATED,
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
        return [event.uid for event in events]

    monkeypatch.setattr(event_processor, "sync_events_to_calendar", _fake_sync)

    uploaded = perform_sync_all(session)

    assert uploaded == 1
    assert captured == [["uid-pending"]]


def test_conflict_details_and_disable_tracking() -> None:
    """Konfliktdetails sollen Unterschiede und Deaktivierungsoption liefern."""

    session = SessionLocal()
    imap, _ = _store_basic_accounts(session)
    start = datetime(2024, 4, 10, 9, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    payload = _build_ical(
        method="REQUEST",
        uid="uid-diff",
        summary="Lokaler Titel",
        start=start,
        end=end,
        status="CONFIRMED",
        description="Lokale Beschreibung",
    )
    event = TrackedEvent(
        uid="uid-diff",
        source_account_id=imap.id,
        source_folder="INBOX",
        summary="Lokaler Titel",
        organizer="orga@example.com",
        start=start,
        end=end,
        status=EventStatus.UPDATED,
        response_status=EventResponseStatus.NONE,
        payload=payload,
        history=[],
        sync_conflict=True,
        sync_conflict_reason="Remote-Version abweichend",
        sync_conflict_snapshot={
            "summary": "Server Titel",
            "start": (start + timedelta(hours=2)).isoformat(),
            "end": (end + timedelta(hours=2)).isoformat(),
            "description": "Server Beschreibung",
            "response_status": EventResponseStatus.ACCEPTED.value,
        },
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    client = TestClient(app)
    response = client.get("/events")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    payload_event = items[0]
    assert payload_event["tracking_disabled"] is False
    details = payload_event["sync_state"]["conflict_details"]
    assert details is not None
    differences = {item["field"]: item for item in details["differences"]}
    assert differences["summary"]["local_value"] == "Lokaler Titel"
    assert differences["summary"]["remote_value"] == "Server Titel"
    assert differences["description"]["remote_value"] == "Server Beschreibung"
    assert differences["response_status"]["remote_value"] == "Zusage"
    assert payload_event["attendees"] == []
    suggestions = {item["action"]: item for item in details["suggestions"]}
    assert set(suggestions) == {
        "overwrite-calendar",
        "skip-email-import",
        "merge-fields",
        "disable-tracking",
    }
    assert suggestions["merge-fields"]["interactive"] is True
    disable_option = next(
        suggestion
        for suggestion in details["suggestions"]
        if suggestion["action"] == "disable-tracking"
    )
    assert disable_option["interactive"] is True

    disable_response = client.post(f"/events/{payload_event['id']}/disable-tracking")
    assert disable_response.status_code == 200
    disabled_payload = disable_response.json()
    assert disabled_payload["tracking_disabled"] is True
    assert disabled_payload["sync_state"]["has_conflict"] is False
    refreshed = client.get("/events")
    assert refreshed.status_code == 200
    assert refreshed.json() == []


def test_resolve_conflict_overwrite_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Das Überschreiben soll die lokale Version exportieren und Konflikte auflösen."""

    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    mapping = SyncMapping(
        imap_account_id=imap.id,
        imap_folder="INBOX",
        caldav_account_id=caldav.id,
        calendar_url="https://cal.example.com/shared",
    )
    session.add(mapping)
    session.commit()
    start = datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    payload = _build_ical(
        method="REQUEST",
        uid="uid-conflict",
        summary="Mail Titel",
        start=start,
        end=end,
        status="CONFIRMED",
    )
    event = TrackedEvent(
        uid="uid-conflict",
        source_account_id=imap.id,
        source_folder="INBOX",
        summary="Mail Titel",
        start=start,
        end=end,
        payload=payload,
        status=EventStatus.UPDATED,
        response_status=EventResponseStatus.NONE,
        history=[],
        sync_conflict=True,
        sync_conflict_reason="Kalender abweichend",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    calls: List[str] = []

    def _fake_force(target: TrackedEvent, calendar_url: str, settings: CalDavSettings) -> None:
        calls.append(target.uid)
        with session_scope() as scoped:
            db_event = scoped.get(TrackedEvent, target.id)
            assert db_event is not None
            db_event.sync_conflict = False
            db_event.sync_conflict_reason = None
            db_event.synced_version = db_event.local_version or 0
            db_event.last_synced = datetime.utcnow()
            scoped.add(db_event)

    monkeypatch.setattr(event_processor, "force_overwrite_event", _fake_force)

    client = TestClient(app)
    response = client.post(
        f"/events/{event.id}/resolve-conflict",
        json={"action": "overwrite-calendar", "selections": {}},
    )
    assert response.status_code == 200
    payload_event = response.json()
    assert payload_event["sync_state"]["has_conflict"] is False
    assert calls == ["uid-conflict"]
    history_descriptions = [entry["description"] for entry in payload_event["history"]]
    assert any(
        "Kalenderdaten wurden mit dem E-Mail-Import überschrieben" in description
        for description in history_descriptions
    )


def test_resolve_conflict_skip_email_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Das Verwerfen soll keinen Export starten und den Konflikt nur temporär ausblenden."""

    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    mapping = SyncMapping(
        imap_account_id=imap.id,
        imap_folder="INBOX",
        caldav_account_id=caldav.id,
        calendar_url="https://cal.example.com/shared",
    )
    session.add(mapping)
    session.commit()
    start = datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    payload = _build_ical(
        method="REQUEST",
        uid="uid-skip",
        summary="Mail Titel",
        start=start,
        end=end,
        status="CONFIRMED",
        description="Mail Beschreibung",
    )
    event = TrackedEvent(
        uid="uid-skip",
        source_account_id=imap.id,
        source_folder="INBOX",
        summary="Mail Titel",
        start=start,
        end=end,
        payload=payload,
        status=EventStatus.UPDATED,
        response_status=EventResponseStatus.NONE,
        history=[],
        sync_conflict=True,
        sync_conflict_reason="Kalender abweichend",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    def _unexpected_remote_call(*_: object, **__: object) -> None:
        raise AssertionError("skip-email-import sollte keine Remote-Daten abrufen")

    monkeypatch.setattr("backend.app.main.get_event_state", _unexpected_remote_call)

    client = TestClient(app)
    response = client.post(
        f"/events/{event.id}/resolve-conflict",
        json={"action": "skip-email-import", "selections": {}},
    )
    assert response.status_code == 200
    payload_event = response.json()
    assert payload_event["sync_state"]["has_conflict"] is False
    assert payload_event["summary"] == "Mail Titel"
    history_descriptions = [entry["description"] for entry in payload_event["history"]]
    assert any("Konflikt verworfen" in description for description in history_descriptions)


def test_resolve_conflict_merge_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Die Zusammenführung soll ausgewählte Felder übernehmen und exportieren."""

    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    mapping = SyncMapping(
        imap_account_id=imap.id,
        imap_folder="INBOX",
        caldav_account_id=caldav.id,
        calendar_url="https://cal.example.com/shared",
    )
    session.add(mapping)
    session.commit()
    start = datetime(2024, 7, 1, 8, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    payload = _build_ical(
        method="REQUEST",
        uid="uid-merge",
        summary="Mail Titel",
        start=start,
        end=end,
        status="CONFIRMED",
        description="Mail Beschreibung",
    )
    event = TrackedEvent(
        uid="uid-merge",
        source_account_id=imap.id,
        source_folder="INBOX",
        summary="Mail Titel",
        start=start,
        end=end,
        payload=payload,
        status=EventStatus.UPDATED,
        response_status=EventResponseStatus.ACCEPTED,
        history=[],
        sync_conflict=True,
        sync_conflict_reason="Kalender abweichend",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    remote_payload = _build_ical(
        method="REQUEST",
        uid="uid-merge",
        summary="Kalender Titel",
        start=start + timedelta(hours=2),
        end=end + timedelta(hours=2),
        status="CONFIRMED",
        description="Kalender Beschreibung",
        location="Konferenzraum",
    )
    remote_state = RemoteEventState(
        uid="uid-merge",
        etag="etag-merge",
        last_modified=datetime.utcnow(),
        payload=remote_payload,
    )

    monkeypatch.setattr("backend.app.main.get_event_state", lambda url, uid, settings: remote_state)

    calls: List[str] = []

    def _fake_force(target: TrackedEvent, calendar_url: str, settings: CalDavSettings) -> None:
        calls.append(target.uid)
        with session_scope() as scoped:
            db_event = scoped.get(TrackedEvent, target.id)
            assert db_event is not None
            db_event.sync_conflict = False
            db_event.sync_conflict_reason = None
            db_event.synced_version = db_event.local_version or 0
            db_event.last_synced = datetime.utcnow()
            scoped.add(db_event)

    monkeypatch.setattr(event_processor, "force_overwrite_event", _fake_force)

    client = TestClient(app)
    response = client.post(
        f"/events/{event.id}/resolve-conflict",
        json={
            "action": "merge-fields",
            "selections": {"summary": "email", "location": "calendar", "response_status": "calendar"},
        },
    )
    assert response.status_code == 200
    payload_event = response.json()
    assert payload_event["sync_state"]["has_conflict"] is False
    assert payload_event["summary"] == "Mail Titel"
    assert payload_event["sync_state"]["conflict_details"] is None
    assert calls == ["uid-merge"]
    assert payload_event["response_status"] == EventResponseStatus.NONE.value
    history_descriptions = [entry["description"] for entry in payload_event["history"]]
    assert any("Daten wurden zusammengeführt" in description for description in history_descriptions)

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


def test_upsert_events_preserves_synced_status_for_identical_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-importing unchanged events must keep their synced status for AutoSync."""

    ics_payload = dedent(
        """
        BEGIN:VCALENDAR
        VERSION:2.0
        PRODID:-//CalSync//Test//DE
        BEGIN:VEVENT
        UID:uid-sync
        SUMMARY:Planungsmeeting
        DTSTART:20240101T090000Z
        DTEND:20240101T100000Z
        ORGANIZER:mailto:orga@example.com
        END:VEVENT
        END:VCALENDAR
        """
    ).encode()

    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    imap_id = imap.id
    mapping = SyncMapping(
        imap_account_id=imap_id,
        imap_folder="INBOX",
        caldav_account_id=caldav.id,
        calendar_url="https://cal.example.com/shared",
    )
    session.add(mapping)
    session.commit()
    session.close()

    parsed_events = parse_ics_payload(ics_payload)
    event_processor.upsert_events(
        parsed_events,
        source_message_id="msg-1",
        source_account_id=imap_id,
        source_folder="INBOX",
    )
    with SessionLocal() as session:
        persisted = session.execute(
            select(TrackedEvent).where(TrackedEvent.uid == "uid-sync")
        ).scalar_one()
        event_id = persisted.id
    event_processor.mark_as_synced([type("EventRef", (), {"id": event_id})()])

    event_processor.upsert_events(
        parse_ics_payload(ics_payload),
        source_message_id="msg-2",
        source_account_id=imap_id,
        source_folder="INBOX",
    )

    with SessionLocal() as session:
        event = session.execute(
            select(TrackedEvent).where(TrackedEvent.uid == "uid-sync")
        ).scalar_one()
        assert event.status == EventStatus.SYNCED
        assert len(event.history or []) == 2
        assert event.mailbox_message_id == "msg-2"

    captured: List[List[str]] = []

    def _fake_sync(events, calendar_url, settings, progress_callback=None):  # pragma: no cover - verification helper
        captured.append([event.uid for event in events])
        return []

    monkeypatch.setattr(event_processor, "sync_events_to_calendar", _fake_sync)

    with SessionLocal() as session:
        uploaded = perform_sync_all(session)

    assert captured == []
    assert uploaded == 0


def test_remote_cancellation_keeps_server_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellations originating in CalDAV must not be removed during sync."""

    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    start = datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    uid = "remote-cancel"
    session.add(
        TrackedEvent(
            uid=uid,
            summary="Team Sync",
            start=start,
            end=end,
            status=EventStatus.SYNCED,
            response_status=EventResponseStatus.NONE,
            source_account_id=imap.id,
            source_folder="INBOX",
            payload=_build_ical(
                method=None,
                uid=uid,
                summary="Team Sync",
                start=start,
                end=end,
                status="CONFIRMED",
            ),
            caldav_etag="etag-old",
            local_version=1,
            synced_version=1,
            history=[],
        )
    )
    session.commit()
    event = session.execute(select(TrackedEvent).where(TrackedEvent.uid == uid)).scalar_one()
    remote_payload = _build_ical(
        method="CANCEL",
        uid=uid,
        summary="Team Sync",
        start=start,
        end=end,
        status="CANCELLED",
    )
    remote_state = RemoteEventState(
        uid=uid,
        etag="etag-new",
        last_modified=end + timedelta(hours=1),
        payload=remote_payload,
    )

    event_processor._apply_remote_snapshot(event, remote_state)

    session.refresh(event)
    assert event.status == EventStatus.CANCELLED
    assert event.cancelled_by_organizer is True
    assert event.last_modified_source == "remote"

    deleted_calls: List[str] = []
    uploaded_calls: List[str] = []
    cancellation_updates: List[Dict[int, tuple[bool, Optional[RemoteEventState]]]] = []

    def _fake_delete(*_args, **_kwargs) -> bool:
        deleted_calls.append("called")
        return False

    def _fake_upload(*_args, **_kwargs):
        uploaded_calls.append("called")
        return remote_state

    def _fake_mark(results):
        cancellation_updates.append(results)

    monkeypatch.setattr("backend.app.services.event_processor.delete_event_by_uid", _fake_delete)
    monkeypatch.setattr("backend.app.services.event_processor.upload_ical", _fake_upload)
    monkeypatch.setattr("backend.app.services.event_processor.mark_as_cancelled", _fake_mark)
    monkeypatch.setattr(
        "backend.app.services.event_processor.get_event_state", lambda *_args, **_kwargs: remote_state
    )

    settings = CalDavSettings(url="https://cal.example.com", username="user", password="secret")
    sync_events = session.execute(select(TrackedEvent).where(TrackedEvent.uid == uid)).scalars().all()
    event_processor.sync_events_to_calendar(sync_events, "https://cal.example.com/shared", settings)

    assert not deleted_calls
    assert not uploaded_calls
    assert cancellation_updates == []


def test_manual_sync_marks_conflicts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Manual sync jobs müssen Konflikte melden statt sie zu exportieren."""

    session = SessionLocal()
    imap, caldav = _store_basic_accounts(session)
    mapping = SyncMapping(
        imap_account_id=imap.id,
        imap_folder="INBOX",
        caldav_account_id=caldav.id,
        calendar_url="https://cal.example.com/shared",
    )
    session.add(mapping)

    event = TrackedEvent(
        uid="uid-conflict",
        status=EventStatus.UPDATED,
        response_status=EventResponseStatus.NONE,
        source_account_id=imap.id,
        source_folder="INBOX",
        start=datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc),
        end=datetime(2024, 3, 1, 10, 0, tzinfo=timezone.utc),
        payload="BEGIN:VEVENT\nUID:uid-conflict\nEND:VEVENT",
        history=[],
        sync_conflict=True,
        sync_conflict_reason="Remote-Version abweichend",
        local_version=2,
        synced_version=1,
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    captured: List[List[str]] = []

    def _fake_sync(events, calendar_url, settings, progress_callback=None):
        captured.append([event.uid for event in events])
        return [event.uid for event in events]

    monkeypatch.setattr(event_processor, "sync_events_to_calendar", _fake_sync)

    state = job_tracker.create("manual-sync", total=1)
    try:
        _execute_manual_sync_job(state.job_id, [event.id])
        final_state = job_tracker.get(state.job_id)
        assert final_state is not None
        assert final_state.status == "completed"
        assert final_state.detail is not None
        detail = final_state.detail
        assert detail.get("uploaded") == []
        missing = detail.get("missing")
        assert missing and missing[0]["event_id"] == event.id
        assert "konflikt" in missing[0]["reason"].lower()
    finally:
        job_tracker._jobs.pop(state.job_id, None)

    assert captured == []


def test_organizer_cancellation_exports_cancel_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Organizer cancellations must be pushed to CalDAV as cancelled events."""

    session = SessionLocal()
    imap, _ = _store_basic_accounts(session)
    start = datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    uid = "local-cancel"
    payload = _build_ical(
        method="CANCEL",
        uid=uid,
        summary="Projektstatus",
        start=start,
        end=end,
        status="CANCELLED",
    )
    parsed = parse_ics_payload(payload.encode())
    stored = event_processor.upsert_events(parsed, "msg-cancel", source_account_id=imap.id, source_folder="INBOX")
    assert stored
    session_event = session.execute(select(TrackedEvent).where(TrackedEvent.uid == uid)).scalar_one()

    uploaded_states: List[RemoteEventState] = []
    deleted_calls: List[str] = []

    def _fake_upload(_url, _ical, _settings):
        state = RemoteEventState(uid=uid, etag="etag-cancel", last_modified=end + timedelta(minutes=5), payload=payload)
        uploaded_states.append(state)
        return state

    def _fake_delete(*_args, **_kwargs) -> bool:
        deleted_calls.append("called")
        return False

    monkeypatch.setattr("backend.app.services.event_processor.upload_ical", _fake_upload)
    monkeypatch.setattr("backend.app.services.event_processor.delete_event_by_uid", _fake_delete)
    monkeypatch.setattr(
        "backend.app.services.event_processor.get_event_state", lambda *_args, **_kwargs: None
    )
    settings = CalDavSettings(url="https://cal.example.com", username="user", password="secret")

    event_processor.sync_events_to_calendar([session_event], "https://cal.example.com/shared", settings)

    assert uploaded_states, "Cancellation should trigger an upload"
    assert not deleted_calls

    with SessionLocal() as verify_session:
        refreshed = verify_session.execute(
            select(TrackedEvent).where(TrackedEvent.uid == uid)
        ).scalar_one()
    assert refreshed.status == EventStatus.CANCELLED
    assert refreshed.history[-1]["description"] == "Kalendereintrag als abgesagt markiert"


def test_remote_reschedule_updates_local_snapshot() -> None:
    """Remote updates must refresh the local copy when no local changes are pending."""

    session = SessionLocal()
    imap, _ = _store_basic_accounts(session)
    start = datetime(2024, 7, 1, 9, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    uid = "remote-update"
    session.add(
        TrackedEvent(
            uid=uid,
            summary="Kickoff",
            start=start,
            end=end,
            status=EventStatus.SYNCED,
            response_status=EventResponseStatus.NONE,
            source_account_id=imap.id,
            source_folder="INBOX",
            payload=_build_ical(
                method=None,
                uid=uid,
                summary="Kickoff",
                start=start,
                end=end,
                status="CONFIRMED",
            ),
            caldav_etag="etag-original",
            local_version=1,
            synced_version=1,
            history=[],
        )
    )
    session.commit()
    event = session.execute(select(TrackedEvent).where(TrackedEvent.uid == uid)).scalar_one()

    new_start = start + timedelta(days=1)
    new_end = new_start + timedelta(hours=1)
    remote_payload = _build_ical(
        method="PUBLISH",
        uid=uid,
        summary="Kickoff",
        start=new_start,
        end=new_end,
        status="CONFIRMED",
    )
    remote_state = RemoteEventState(
        uid=uid,
        etag="etag-updated",
        last_modified=new_end,
        payload=remote_payload,
    )

    event_processor._apply_remote_snapshot(event, remote_state)

    with SessionLocal() as verify_session:
        updated = verify_session.execute(
            select(TrackedEvent).where(TrackedEvent.uid == uid)
        ).scalar_one()
    assert updated.start == new_start.replace(tzinfo=None)
    assert updated.end == new_end.replace(tzinfo=None)
    assert updated.status == EventStatus.SYNCED
    assert updated.last_modified_source == "remote"
    assert updated.caldav_etag == "etag-updated"
