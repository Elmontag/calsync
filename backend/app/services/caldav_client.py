"""Helpers for interacting with CalDAV calendars."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from caldav import DAVClient
from caldav.objects import Calendar
from icalendar import Calendar as ICalendar

logger = logging.getLogger(__name__)


@dataclass
class CalDavSettings:
    url: str
    username: Optional[str] = None
    password: Optional[str] = None


class CalDavConnection:
    """Context manager for CalDAV operations."""

    def __init__(self, settings: CalDavSettings):
        self.settings = settings
        self._client: Optional[DAVClient] = None

    def __enter__(self) -> DAVClient:
        logger.debug("Connecting to CalDAV endpoint %s", self.settings.url)
        self._client = DAVClient(
            url=self.settings.url,
            username=self.settings.username,
            password=self.settings.password,
        )
        return self._client

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        logger.debug("Leaving CalDAV context")


def upload_ical(calendar_url: str, ical: ICalendar, settings: CalDavSettings) -> None:
    """Upload a parsed calendar event to the given calendar."""
    with CalDavConnection(settings) as client:
        principal = client.principal()
        calendar: Calendar = principal.calendar(cal_url=calendar_url)
        logger.info("Uploading event %s to %s", ical.get("UID"), calendar_url)
        calendar.save_event(ical.to_ical())


def delete_event_by_uid(calendar_url: str, uid: str, settings: CalDavSettings) -> bool:
    """Delete an event identified by UID from the CalDAV calendar if present."""
    with CalDavConnection(settings) as client:
        principal = client.principal()
        calendar: Calendar = principal.calendar(cal_url=calendar_url)
        try:
            event = calendar.event_by_uid(uid)
        except Exception:  # pragma: no cover - depends on CalDAV server responses
            logger.info("No calendar entry found for UID %s in %s", uid, calendar_url)
            return False
        try:
            event.delete()
            logger.info("Removed calendar entry %s from %s", uid, calendar_url)
            return True
        except Exception:  # pragma: no cover - depends on CalDAV server responses
            logger.exception("Failed to remove calendar entry %s from %s", uid, calendar_url)
            return False


def _ensure_datetime(value: datetime | date) -> datetime:
    """Normalize CalDAV date or datetime values to timezone-aware datetimes."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)


def _extract_component_range(component) -> tuple[Optional[datetime], Optional[datetime]]:
    """Derive the time range for a VEVENT component."""
    start_raw = component.get("DTSTART")
    end_raw = component.get("DTEND")
    start = _ensure_datetime(start_raw.dt) if start_raw else None
    end = _ensure_datetime(end_raw.dt) if end_raw else None
    if end is None and start is not None:
        # Default to a 30 minute slot if no explicit end is provided.
        end = start + timedelta(minutes=30)
    return start, end


def _ranges_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Return True if the provided date ranges overlap."""
    latest_start = max(a_start, b_start)
    earliest_end = min(a_end, b_end)
    return latest_start < earliest_end


def find_conflicting_events(
    calendar: Calendar,
    start: datetime,
    end: datetime,
    *,
    exclude_uid: Optional[str] = None,
) -> List[Dict[str, Optional[str]]]:
    """Locate CalDAV events overlapping with the provided time range."""
    try:
        matches = calendar.date_search(start, end)
    except Exception:  # pragma: no cover - network interaction
        logger.exception("CalDAV search failed for range %s - %s", start, end)
        return []

    conflicts: List[Dict[str, Optional[str]]] = []
    seen_uids: set[str] = set()
    for match in matches:
        try:
            payload = match.data
        except Exception:  # pragma: no cover - depends on CalDAV implementation
            logger.warning("Skipped CalDAV entry without accessible payload")
            continue
        calendar_payload = ICalendar.from_ical(payload)
        for component in calendar_payload.walk("VEVENT"):
            uid = str(component.get("UID"))
            if exclude_uid and uid == exclude_uid:
                continue
            if uid in seen_uids:
                continue
            comp_start, comp_end = _extract_component_range(component)
            if comp_start is None or comp_end is None:
                continue
            if _ranges_overlap(start, end, comp_start, comp_end):
                seen_uids.add(uid)
                conflicts.append(
                    {
                        "uid": uid,
                        "summary": str(component.get("SUMMARY") or "Unbenannter Termin"),
                        "start": comp_start.isoformat(),
                        "end": comp_end.isoformat(),
                    }
                )
    return conflicts


def list_calendars(settings: CalDavSettings) -> Iterable[Dict[str, str]]:
    """Return all calendar URLs accessible with the given credentials."""
    with CalDavConnection(settings) as client:
        principal = client.principal()
        for calendar in principal.calendars():
            calendar_url = str(calendar.url)
            yield {
                "url": calendar_url,
                "name": getattr(calendar, "name", None) or calendar_url,
            }
