"""High-level orchestration for syncing calendar data."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select

from ..database import session_scope
from ..models import EventResponseStatus, EventStatus, TrackedEvent
from ..utils.ics_parser import ParsedEvent, merge_histories
from .caldav_client import CalDavSettings, delete_event_by_uid, upload_ical

logger = logging.getLogger(__name__)


def upsert_events(
    parsed_events: Iterable[ParsedEvent],
    source_message_id: str,
    source_account_id: Optional[int] = None,
    source_folder: Optional[str] = None,
) -> List[TrackedEvent]:
    """Insert new or update existing events based on parsed ICS data."""
    stored_events: List[TrackedEvent] = []
    with session_scope() as session:
        for parsed in parsed_events:
            event: TrackedEvent | None = session.execute(
                select(TrackedEvent).where(TrackedEvent.uid == parsed.uid)
            ).scalar_one_or_none()
            history_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "action": parsed.status.value,
                "description": f"Event processed from message {source_message_id}",
            }
            if event is None:
                event = TrackedEvent(
                    uid=parsed.uid,
                    source_account_id=source_account_id,
                    source_folder=source_folder,
                    summary=parsed.summary,
                    organizer=parsed.organizer,
                    start=parsed.start,
                    end=parsed.end,
                    status=parsed.status,
                    response_status=EventResponseStatus.NONE,
                    mailbox_message_id=source_message_id,
                    payload=parsed.event.to_ical().decode(),
                    history=[history_entry],
                )
                session.add(event)
                logger.info("Stored new event %s", parsed.uid)
            else:
                event.summary = parsed.summary
                event.organizer = parsed.organizer
                event.start = parsed.start
                event.end = parsed.end
                event.payload = parsed.event.to_ical().decode()
                event.status = parsed.status if parsed.status != EventStatus.NEW else EventStatus.UPDATED
                event.source_account_id = source_account_id or event.source_account_id
                event.source_folder = source_folder or event.source_folder
                event.history = merge_histories(event.history or [], history_entry)
                event.updated_at = datetime.utcnow()
                logger.info("Updated event %s", parsed.uid)
            stored_events.append(event)
    return stored_events


def mark_as_synced(events: Iterable[TrackedEvent]) -> None:
    """Mark events as synced in the database."""
    events_list = list(events)
    with session_scope() as session:
        for event in events_list:
            db_event = session.get(TrackedEvent, event.id)
            if db_event is None:
                continue
            db_event.status = EventStatus.SYNCED
            db_event.last_synced = datetime.utcnow()
            db_event.history = merge_histories(
                db_event.history or [],
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": EventStatus.SYNCED.value,
                    "description": "Event exported to CalDAV",
                },
            )
            session.add(db_event)
    logger.debug("Marked %s events as synced", len(events_list))


def sync_events_to_calendar(
    events: Iterable[TrackedEvent],
    calendar_url: str,
    settings: CalDavSettings,
) -> List[str]:
    """Upload a batch of events to the configured CalDAV calendar."""
    uploaded_uids: List[str] = []
    events_list = list(events)
    successfully_uploaded: List[TrackedEvent] = []
    cancellation_results: Dict[int, bool] = {}
    for event in events_list:
        if event.status == EventStatus.CANCELLED:
            removed = delete_event_by_uid(calendar_url, event.uid, settings)
            cancellation_results[event.id] = removed
            continue
        try:
            upload_ical(calendar_url, event_payload_to_ical(event), settings)
            uploaded_uids.append(event.uid)
            successfully_uploaded.append(event)
        except Exception:
            logger.exception("Failed to upload event %s", event.uid)
            continue
    if successfully_uploaded:
        mark_as_synced(successfully_uploaded)
    elif not cancellation_results:
        logger.warning("No events could be synced to %s", calendar_url)
    if cancellation_results:
        mark_as_cancelled(cancellation_results)
    return uploaded_uids


def event_payload_to_ical(event: TrackedEvent):
    from icalendar import Calendar

    cal = Calendar.from_ical(event.payload)
    return cal


def annotate_response(event: TrackedEvent) -> None:
    """Embed the stored response status within the ICS payload for CalDAV."""
    from icalendar import Calendar

    calendar = Calendar.from_ical(event.payload)
    updated = False
    for component in calendar.walk("VEVENT"):
        component["X-CALSYNC-RESPONSE"] = event.response_status.value.upper()
        updated = True
    if updated:
        event.payload = calendar.to_ical().decode()


def mark_as_cancelled(results: Dict[int, bool]) -> None:
    """Update cancellation attempts with a history entry and timestamp."""
    with session_scope() as session:
        for event_id, removed in results.items():
            event = session.get(TrackedEvent, event_id)
            if event is None:
                continue
            event.status = EventStatus.CANCELLED
            event.last_synced = datetime.utcnow()
            description = (
                "Termin im Kalender entfernt"
                if removed
                else "Kein Kalendereintrag zum Entfernen gefunden"
            )
            event.history = merge_histories(
                event.history or [],
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": EventStatus.CANCELLED.value,
                    "description": description,
                },
            )
            session.add(event)
    logger.info("Processed %s cancellation updates", len(results))
