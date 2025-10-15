"""High-level orchestration for syncing calendar data."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

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
            cancelled_by_organizer: Optional[bool] = None
            if parsed.status == EventStatus.CANCELLED:
                cancelled_by_organizer = (parsed.method or "").upper() == "CANCEL"
            event: TrackedEvent | None = session.execute(
                select(TrackedEvent).where(TrackedEvent.uid == parsed.uid)
            ).scalar_one_or_none()
            history_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "action": parsed.status.value,
                "description": f"Event processed from message {source_message_id}",
            }
            if parsed.response_status is not None:
                history_entry["description"] = (
                    f"{history_entry['description']} · Antwort: {parsed.response_status.value}"
                )
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
                    response_status=parsed.response_status or EventResponseStatus.NONE,
                    cancelled_by_organizer=cancelled_by_organizer,
                    mailbox_message_id=source_message_id,
                    payload=parsed.event.to_ical().decode(),
                    history=[history_entry],
                )
                if parsed.response_status is not None:
                    annotate_response(event)
                session.add(event)
                logger.info("Stored new event %s", parsed.uid)
            else:
                new_payload = parsed.event.to_ical().decode()
                previous_status = event.status
                content_changed = False
                metadata_changed = False
                response_changed = False

                def _normalize_datetime(value: datetime) -> datetime:
                    if value.tzinfo is not None:
                        return value.astimezone(timezone.utc).replace(tzinfo=None)
                    return value

                def _update(attr: str, value, *, track_content: bool = True) -> None:
                    nonlocal content_changed, metadata_changed
                    current = getattr(event, attr)
                    new_value = value
                    if isinstance(current, datetime) and isinstance(value, datetime):
                        current_normalized = _normalize_datetime(current)
                        new_normalized = _normalize_datetime(value)
                        if current_normalized == new_normalized:
                            return
                        new_value = new_normalized
                    elif isinstance(value, datetime) and current is None:
                        new_value = _normalize_datetime(value)
                    if current == new_value:
                        return
                    setattr(event, attr, new_value)
                    if track_content:
                        content_changed = True
                    else:
                        metadata_changed = True

                _update("summary", parsed.summary)
                _update("organizer", parsed.organizer)
                _update("start", parsed.start)
                _update("end", parsed.end)
                _update("payload", new_payload)

                reopened = previous_status == EventStatus.CANCELLED and parsed.status != EventStatus.CANCELLED
                if reopened:
                    content_changed = True

                if parsed.status == EventStatus.CANCELLED:
                    _update("cancelled_by_organizer", cancelled_by_organizer)
                else:
                    _update("cancelled_by_organizer", None)

                if source_account_id is not None:
                    _update("source_account_id", source_account_id, track_content=False)
                if source_folder is not None:
                    _update("source_folder", source_folder, track_content=False)
                _update("mailbox_message_id", source_message_id, track_content=False)

                if parsed.response_status is not None and parsed.response_status != event.response_status:
                    event.response_status = parsed.response_status
                    annotate_response(event)
                    content_changed = True
                    response_changed = True

                status_changed = False
                if parsed.status == EventStatus.CANCELLED:
                    if event.status != EventStatus.CANCELLED:
                        event.status = EventStatus.CANCELLED
                        status_changed = True
                else:
                    if content_changed and event.status != EventStatus.NEW:
                        if event.status != EventStatus.UPDATED:
                            event.status = EventStatus.UPDATED
                            status_changed = True
                    elif reopened:
                        if event.status != EventStatus.UPDATED:
                            event.status = EventStatus.UPDATED
                            status_changed = True

                should_append_history = content_changed or status_changed or response_changed
                if should_append_history:
                    event.history = merge_histories(event.history or [], history_entry)
                if content_changed or metadata_changed or status_changed:
                    event.updated_at = datetime.utcnow()
                    session.add(event)

                if content_changed or status_changed or response_changed:
                    logger.info("Updated event %s", parsed.uid)
                elif metadata_changed:
                    logger.debug("Updated metadata for event %s without content changes", parsed.uid)
                else:
                    logger.debug("No changes detected for event %s", parsed.uid)
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
    progress_callback: Optional[Callable[[TrackedEvent, bool], None]] = None,
) -> List[str]:
    """Upload a batch of events to the configured CalDAV calendar."""
    uploaded_uids: List[str] = []
    events_list = list(events)
    successfully_uploaded: List[TrackedEvent] = []
    cancellation_results: Dict[int, bool] = {}
    ignored_cancellations: List[TrackedEvent] = []
    for event in events_list:
        if event.status == EventStatus.CANCELLED:
            if getattr(event, "cancelled_by_organizer", None) is False:
                logger.info(
                    "Skipping calendar removal for %s because cancellation was not initiated by the organizer",
                    event.uid,
                )
                ignored_cancellations.append(event)
                if progress_callback is not None:
                    progress_callback(event, True)
                continue
            removed = delete_event_by_uid(calendar_url, event.uid, settings)
            cancellation_results[event.id] = removed
            if progress_callback is not None:
                progress_callback(event, removed)
            continue
        success = False
        try:
            upload_ical(calendar_url, event_payload_to_ical(event), settings)
            uploaded_uids.append(event.uid)
            successfully_uploaded.append(event)
            success = True
        except Exception:
            logger.exception("Failed to upload event %s", event.uid)
            continue
        finally:
            if progress_callback is not None:
                progress_callback(event, success)
    if successfully_uploaded:
        mark_as_synced(successfully_uploaded)
    elif not cancellation_results:
        logger.warning("No events could be synced to %s", calendar_url)
    if cancellation_results:
        mark_as_cancelled(cancellation_results)
    if ignored_cancellations:
        mark_cancellations_ignored(ignored_cancellations)
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


def mark_cancellations_ignored(events: Iterable[TrackedEvent]) -> None:
    """Record ignored cancellation requests triggered by attendees."""

    events_list = list(events)
    if not events_list:
        return
    with session_scope() as session:
        for event in events_list:
            db_event = session.get(TrackedEvent, event.id)
            if db_event is None:
                continue
            db_event.last_synced = datetime.utcnow()
            db_event.history = merge_histories(
                db_event.history or [],
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": EventStatus.CANCELLED.value,
                    "description": "Absage ignoriert (nicht vom Ersteller)",
                },
            )
            session.add(db_event)
    logger.info("Ignored %s attendee cancellations", len(events_list))
