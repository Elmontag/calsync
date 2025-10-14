"""Utility helpers to parse ICS payloads."""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Iterable, List, Optional

from icalendar import Calendar, Event
from pydantic import BaseModel, ConfigDict

from ..models import EventResponseStatus, EventStatus

logger = logging.getLogger(__name__)


class ParsedEvent(BaseModel):
    uid: str
    summary: Optional[str]
    organizer: Optional[str]
    start: Optional[datetime]
    end: Optional[datetime]
    status: EventStatus
    event: Event
    method: Optional[str] = None
    response_status: Optional[EventResponseStatus] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


def parse_ics_payload(payload: bytes) -> List[ParsedEvent]:
    """Parse an ICS payload and extract event information."""
    calendar = Calendar.from_ical(payload)
    method_raw = calendar.get("METHOD")
    method = str(method_raw).upper() if method_raw else None
    events: List[ParsedEvent] = []
    for component in calendar.walk("VEVENT"):
        uid = str(component.get("UID"))
        summary = component.get("SUMMARY")
        organizer = component.get("ORGANIZER")
        status_raw = (component.get("STATUS") or "CONFIRMED").upper()
        status = {
            "CONFIRMED": EventStatus.NEW,
            "TENTATIVE": EventStatus.NEW,
            "CANCELLED": EventStatus.CANCELLED,
        }.get(status_raw, EventStatus.NEW)
        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        start = _normalize_date(dtstart.dt) if dtstart else None
        end = _normalize_date(dtend.dt) if dtend else None
        response_status: Optional[EventResponseStatus] = None
        if method == "REPLY":
            attendees_raw = component.get("ATTENDEE")
            attendees = attendees_raw if isinstance(attendees_raw, list) else [attendees_raw]
            partstat_map = {
                "ACCEPTED": EventResponseStatus.ACCEPTED,
                "TENTATIVE": EventResponseStatus.TENTATIVE,
                "DECLINED": EventResponseStatus.DECLINED,
            }
            for attendee in attendees:
                if not attendee:
                    continue
                params = getattr(attendee, "params", {})
                partstat = str(params.get("PARTSTAT", "")).upper()
                if partstat in partstat_map:
                    response_status = partstat_map[partstat]
                    logger.debug("Detected RSVP response %s for UID %s", partstat, uid)
                    break
        events.append(
            ParsedEvent(
                uid=uid,
                summary=str(summary) if summary else None,
                organizer=str(organizer) if organizer else None,
                start=start,
                end=end,
                status=status,
                event=component,
                method=method,
                response_status=response_status,
            )
        )
    logger.debug("Parsed %s events from ICS", len(events))
    return events


def merge_histories(existing: Iterable[dict], new_entry: dict) -> List[dict]:
    """Append a new history entry to an existing history list."""
    history = list(existing)
    history.append(new_entry)
    return history


def _normalize_date(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        # All-day events are represented as date objects in ICS payloads. Normalize
        # them to datetimes at midnight to ensure consistent handling downstream.
        return datetime.combine(value, time.min)
    if hasattr(value, "to_datetime"):
        return value.to_datetime()
    raise TypeError(f"Unsupported date value: {value!r}")
