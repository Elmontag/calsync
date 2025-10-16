"""Tests for parsing calendar payloads."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.app.utils.ics_parser import parse_ics_payload


def test_parse_ics_payload_accepts_vcs_payload() -> None:
    """vCalendar payloads should be parsed identically to ICS files."""

    payload = (
        "BEGIN:VCALENDAR\n"
        "VERSION:1.0\n"
        "BEGIN:VEVENT\n"
        "UID:test-vcs\n"
        "DTSTART:20240101T120000Z\n"
        "DTEND:20240101T130000Z\n"
        "SUMMARY:Besprechung\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    ).encode()

    events = parse_ics_payload(payload)

    assert len(events) == 1
    event = events[0]
    assert event.uid == "test-vcs"
    assert event.summary == "Besprechung"
    assert event.start == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert event.end == datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)
