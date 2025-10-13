"""Helpers for interacting with CalDAV calendars."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

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
        calendar: Calendar = principal.calendar(url=calendar_url)
        logger.info("Uploading event %s to %s", ical.get("UID"), calendar_url)
        calendar.save_event(ical.to_ical())


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
