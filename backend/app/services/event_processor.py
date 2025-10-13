"""High-level orchestration for syncing calendar data."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, List

from sqlalchemy import select

from ..database import session_scope
from ..models import EventStatus, TrackedEvent
from ..schemas import ManualSyncRequest
from ..utils.ics_parser import ParsedEvent, merge_histories
from .caldav_client import CalDavSettings, upload_ical

logger = logging.getLogger(__name__)


def upsert_events(parsed_events: Iterable[ParsedEvent], source_message_id: str) -> List[TrackedEvent]:
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
                    summary=parsed.summary,
                    organizer=parsed.organizer,
                    start=parsed.start,
                    end=parsed.end,
                    status=parsed.status,
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


def manual_sync(request: ManualSyncRequest, settings: CalDavSettings) -> List[str]:
    """Manually export selected events to a CalDAV calendar."""
    uploaded_uids: List[str] = []
    with session_scope() as session:
        events = list(
            session.execute(
                select(TrackedEvent).where(TrackedEvent.id.in_(request.event_ids))
            ).scalars()
        )
        for event in events:
            try:
                upload_ical(request.target_calendar, event_payload_to_ical(event), settings)
                uploaded_uids.append(event.uid)
            except Exception:
                logger.exception("Failed to upload event %s", event.uid)
                continue
        mark_as_synced(events)
    return uploaded_uids


def event_payload_to_ical(event: TrackedEvent):
    from icalendar import Calendar

    cal = Calendar.from_ical(event.payload)
    return cal
