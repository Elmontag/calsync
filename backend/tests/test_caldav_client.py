from datetime import datetime, timezone
from pathlib import Path
import sys

from caldav.elements import dav

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover - test bootstrap code
    sys.path.insert(0, str(ROOT))

from backend.app.services import caldav_client


ICS_PAYLOAD = """BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Calsync Tests//DE\nBEGIN:VEVENT\nUID:test-uid\nDTSTAMP:20240101T120000Z\nLAST-MODIFIED:20240101T121500Z\nSUMMARY:Konfliktpruefung\nDTSTART:20240101T120000Z\nDTEND:20240101T130000Z\nEND:VEVENT\nEND:VCALENDAR\n"""


class _FakeEvent:
    def __init__(self, payload: str, *, props: dict | None = None) -> None:
        self.data = payload
        self.props = props or {}
        self.property_requests = 0

    def get_properties(self, requested):
        self.property_requests += 1
        assert len(requested) == 1
        assert getattr(requested[0], "tag", None) == dav.GetEtag.tag
        # Simulate a PROPFIND response populating the cached props dictionary.
        self.props[dav.GetEtag.tag] = 'W/"etag-from-server"'
        return self.props


class _FakeCalendar:
    def __init__(self, event: _FakeEvent) -> None:
        self._event = event

    def event_by_uid(self, uid: str):
        assert uid == "test-uid"
        return self._event


def test_fetch_event_state_populates_etag_via_properties() -> None:
    calendar = _FakeCalendar(_FakeEvent(ICS_PAYLOAD))

    state = caldav_client._fetch_event_state(calendar, "test-uid")

    assert state is not None
    assert state.etag == 'W/"etag-from-server"'
    assert state.last_modified == datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
    assert state.payload == ICS_PAYLOAD
    # ensure we actually triggered the PROPFIND for getetag
    assert calendar._event.property_requests == 1


def test_fetch_event_state_reuses_cached_etag_without_extra_call() -> None:
    event = _FakeEvent(ICS_PAYLOAD, props={dav.GetEtag.tag: '"cached-etag"'})
    calendar = _FakeCalendar(event)

    state = caldav_client._fetch_event_state(calendar, "test-uid")

    assert state is not None
    assert state.etag == '"cached-etag"'
    assert state.last_modified == datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
    assert calendar._event.property_requests == 0
