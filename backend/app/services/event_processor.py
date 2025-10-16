"""High-level orchestration for syncing calendar data."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

from sqlalchemy import select

from ..database import session_scope
from ..models import EventResponseStatus, EventStatus, TrackedEvent
from ..utils.ics_parser import (
    ParsedEvent,
    extract_event_snapshot,
    merge_histories,
    parse_ics_payload,
)
from .caldav_client import (
    CalDavSettings,
    RemoteEventState,
    delete_event_by_uid,
    get_event_state,
    upload_ical,
)

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
            now = datetime.utcnow()
            history_entry = {
                "timestamp": now.isoformat(),
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
                    local_version=1,
                    synced_version=0,
                    local_last_modified=now,
                    last_modified_source="local",
                    sync_conflict=False,
                    sync_conflict_reason=None,
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
                    if content_changed or status_changed or response_changed:
                        event.local_version = (event.local_version or 0) + 1
                        event.local_last_modified = datetime.utcnow()
                        event.last_modified_source = "local"
                        event.sync_conflict = False
                        event.sync_conflict_reason = None
                        event.sync_conflict_snapshot = None
                    session.add(event)

                if content_changed or status_changed or response_changed:
                    logger.info("Updated event %s", parsed.uid)
                elif metadata_changed:
                    logger.debug("Updated metadata for event %s without content changes", parsed.uid)
                else:
                    logger.debug("No changes detected for event %s", parsed.uid)
            stored_events.append(event)
    return stored_events


def mark_as_synced(
    events: Iterable[TrackedEvent],
    *,
    remote_states: Optional[Dict[int, RemoteEventState]] = None,
) -> None:
    """Mark events as synced in the database and persist metadata from CalDAV."""

    events_list = list(events)
    state_index = remote_states or {}
    with session_scope() as session:
        for event in events_list:
            db_event = session.get(TrackedEvent, event.id)
            if db_event is None:
                continue
            remote_state = state_index.get(event.id)
            db_event.status = EventStatus.SYNCED
            db_event.last_synced = datetime.utcnow()
            db_event.synced_version = db_event.local_version or 0
            db_event.sync_conflict = False
            db_event.sync_conflict_reason = None
            db_event.last_modified_source = db_event.last_modified_source or "local"
            if db_event.local_last_modified is None:
                db_event.local_last_modified = datetime.utcnow()
            if remote_state is not None:
                db_event.caldav_etag = remote_state.etag
                db_event.remote_last_modified = remote_state.last_modified
            db_event.sync_conflict_snapshot = None
            db_event.history = merge_histories(
                db_event.history or [],
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": EventStatus.SYNCED.value,
                    "description": "Event exported to CalDAV",
                },
            )
            db_event.updated_at = datetime.utcnow()
            session.add(db_event)
    logger.debug("Marked %s events as synced", len(events_list))


def sync_events_to_calendar(
    events: Iterable[TrackedEvent],
    calendar_url: str,
    settings: CalDavSettings,
    progress_callback: Optional[Callable[[TrackedEvent, bool], None]] = None,
) -> List[str]:
    """Upload a batch of events to the configured CalDAV calendar."""

    def _normalize_to_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    uploaded_uids: List[str] = []
    events_list = list(events)
    successfully_uploaded: List[TrackedEvent] = []
    remote_states: Dict[int, RemoteEventState] = {}
    cancellation_results: Dict[int, tuple[bool, Optional[RemoteEventState]]] = {}
    ignored_cancellations: List[TrackedEvent] = []
    conflicts_detected = 0
    for event in events_list:
        remote_state: Optional[RemoteEventState] = None
        try:
            remote_state = get_event_state(calendar_url, event.uid, settings)
        except Exception:
            logger.exception("Failed to load remote state for %s", event.uid)

        known_etag = getattr(event, "caldav_etag", None)
        has_local_changes = (event.local_version or 0) > (event.synced_version or 0)

        remote_change_detected = False
        conflict_reason: Optional[str] = None
        default_conflict_reason = (
            "Kalendereintrag wurde in den Kalenderdaten verändert. Anpassungen aus dem E-Mail-Import wurden nicht überschrieben."
        )
        if remote_state is not None:
            if remote_state.etag and known_etag and remote_state.etag != known_etag:
                remote_change_detected = True
                conflict_reason = default_conflict_reason
            else:
                remote_last_modified = _normalize_to_utc(remote_state.last_modified)
                known_remote_last_modified = _normalize_to_utc(
                    getattr(event, "remote_last_modified", None)
                )
                baseline = known_remote_last_modified or _normalize_to_utc(
                    getattr(event, "last_synced", None)
                )
                if remote_last_modified and baseline and remote_last_modified > baseline:
                    logger.info(
                        "Detected remote change for %s via timestamp comparison (known=%s, remote=%s)",
                        event.uid,
                        baseline.isoformat(),
                        remote_last_modified.isoformat(),
                    )
                    remote_change_detected = True
                    conflict_reason = (
                        "Kalendereintrag wurde im Kalender nach der letzten Synchronisierung verändert (Zeitstempel). "
                        "Anpassungen aus dem E-Mail-Import wurden nicht überschrieben."
                    )

        if remote_change_detected and remote_state is not None:
            if has_local_changes:
                conflicts_detected += 1
                _record_sync_conflict(
                    event,
                    conflict_reason or default_conflict_reason,
                    remote_state,
                )
                if progress_callback is not None:
                    progress_callback(event, False)
                continue
            _apply_remote_snapshot(event, remote_state)
            if progress_callback is not None:
                progress_callback(event, True)
            continue

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
            if (
                not has_local_changes
                and getattr(event, "last_modified_source", None) == "remote"
            ):
                logger.debug(
                    "Skipping cancellation export for %s because the change originated from CalDAV",
                    event.uid,
                )
                if progress_callback is not None:
                    progress_callback(event, True)
                continue
            if not event.payload:
                logger.warning(
                    "Cancellation payload missing for %s – falling back to deletion",
                    event.uid,
                )
                removed = delete_event_by_uid(calendar_url, event.uid, settings)
                cancellation_results[event.id] = (removed, remote_state)
                if progress_callback is not None:
                    progress_callback(event, removed)
                continue
            success = False
            new_state: Optional[RemoteEventState] = None
            try:
                new_state = upload_ical(calendar_url, event_payload_to_ical(event), settings)
                cancellation_results[event.id] = (True, new_state or remote_state)
                success = True
            except Exception:
                logger.exception("Failed to upload cancellation for event %s", event.uid)
                cancellation_results[event.id] = (False, remote_state)
            finally:
                if success and new_state is None:
                    try:
                        refreshed_state = get_event_state(calendar_url, event.uid, settings)
                        if refreshed_state is not None:
                            cancellation_results[event.id] = (True, refreshed_state)
                    except Exception:
                        logger.exception("Failed to refresh remote state for %s", event.uid)
                if progress_callback is not None:
                    progress_callback(event, success)
            continue
        success = False
        new_state: Optional[RemoteEventState] = None
        try:
            new_state = upload_ical(calendar_url, event_payload_to_ical(event), settings)
            uploaded_uids.append(event.uid)
            successfully_uploaded.append(event)
            if new_state is not None:
                remote_states[event.id] = new_state
            success = True
        except Exception:
            logger.exception("Failed to upload event %s", event.uid)
            if remote_state is not None:
                remote_states.setdefault(event.id, remote_state)
            continue
        finally:
            if success and new_state is None:
                try:
                    refreshed_state = get_event_state(calendar_url, event.uid, settings)
                    if refreshed_state is not None:
                        remote_states[event.id] = refreshed_state
                except Exception:
                    logger.exception("Failed to refresh remote state for %s", event.uid)
            if progress_callback is not None:
                progress_callback(event, success)
    if successfully_uploaded:
        mark_as_synced(successfully_uploaded, remote_states=remote_states)
    elif not cancellation_results and conflicts_detected == 0:
        logger.warning("No events could be synced to %s", calendar_url)
    if cancellation_results:
        mark_as_cancelled(cancellation_results)
    if ignored_cancellations:
        mark_cancellations_ignored(ignored_cancellations)
    return uploaded_uids


def force_overwrite_event(
    event: TrackedEvent,
    calendar_url: str,
    settings: CalDavSettings,
) -> None:
    """Upload the local event payload to CalDAV, ignoring version conflicts."""

    remote_state: Optional[RemoteEventState] = None
    try:
        remote_state = get_event_state(calendar_url, event.uid, settings)
    except Exception:
        logger.exception("Failed to inspect remote state before overwrite for %s", event.uid)

    new_state: Optional[RemoteEventState] = None
    try:
        new_state = upload_ical(calendar_url, event_payload_to_ical(event), settings)
        logger.info("Overwrote remote event %s with local data", event.uid)
    except Exception:
        logger.exception("Forced overwrite for event %s failed", event.uid)
        raise
    finally:
        if new_state is None and remote_state is None:
            try:
                remote_state = get_event_state(calendar_url, event.uid, settings)
            except Exception:
                logger.exception("Failed to refresh remote state after overwrite for %s", event.uid)

    effective_state: Optional[RemoteEventState] = new_state or remote_state
    if effective_state is not None:
        mark_as_synced([event], remote_states={event.id: effective_state})
    else:
        mark_as_synced([event])


def apply_remote_version(event: TrackedEvent, remote_state: RemoteEventState) -> None:
    """Persist the remote calendar version locally during conflict resolution."""

    _apply_remote_snapshot(event, remote_state)


def _record_sync_conflict(
    event: TrackedEvent, reason: str, remote_state: Optional[RemoteEventState]
) -> None:
    """Persist a conflict entry for manual resolution."""

    with session_scope() as session:
        db_event = session.get(TrackedEvent, event.id)
        if db_event is None:
            return
        db_event.sync_conflict = True
        db_event.sync_conflict_reason = reason
        if remote_state is not None:
            if remote_state.etag:
                db_event.caldav_etag = remote_state.etag
            db_event.remote_last_modified = remote_state.last_modified
            snapshot = None
            if remote_state.payload:
                try:
                    snapshot = extract_event_snapshot(remote_state.payload, uid=event.uid)
                except Exception:
                    logger.exception("Failed to capture conflict snapshot for %s", event.uid)
            db_event.sync_conflict_snapshot = snapshot
        else:
            db_event.sync_conflict_snapshot = None
        db_event.history = merge_histories(
            db_event.history or [],
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": "conflict",
                "description": reason,
            },
        )
        db_event.updated_at = datetime.utcnow()
        session.add(db_event)
    logger.warning("Detected CalDAV conflict for event %s", event.uid)


def _apply_remote_snapshot(
    event: TrackedEvent, remote_state: RemoteEventState
) -> None:
    """Apply the remote calendar version locally when no local changes exist."""

    if not remote_state.payload:
        logger.debug("Remote state for %s lacks payload; skipping update", event.uid)
        return

    payload_bytes = (
        remote_state.payload.encode()
        if isinstance(remote_state.payload, str)
        else remote_state.payload
    )
    if not isinstance(payload_bytes, (bytes, bytearray)):
        logger.debug("Remote payload for %s not convertible to bytes", event.uid)
        return

    parsed_events = parse_ics_payload(bytes(payload_bytes))
    if not parsed_events:
        logger.debug("Remote payload for %s does not contain events", event.uid)
        return
    selected = next((item for item in parsed_events if item.uid == event.uid), parsed_events[0])
    cancelled_by_organizer: Optional[bool] = None
    if selected.status == EventStatus.CANCELLED:
        cancelled_by_organizer = (selected.method or "").upper() == "CANCEL"

    with session_scope() as session:
        db_event = session.get(TrackedEvent, event.id)
        if db_event is None:
            return
        db_event.summary = selected.summary
        db_event.organizer = selected.organizer
        db_event.start = selected.start
        db_event.end = selected.end
        db_event.payload = remote_state.payload
        db_event.status = EventStatus.SYNCED if selected.status != EventStatus.CANCELLED else EventStatus.CANCELLED
        db_event.cancelled_by_organizer = cancelled_by_organizer
        db_event.caldav_etag = remote_state.etag
        db_event.remote_last_modified = remote_state.last_modified
        db_event.synced_version = db_event.local_version or 0
        db_event.last_synced = datetime.utcnow()
        db_event.local_last_modified = remote_state.last_modified or db_event.local_last_modified
        db_event.last_modified_source = "remote"
        db_event.sync_conflict = False
        db_event.sync_conflict_reason = None
        db_event.sync_conflict_snapshot = None
        db_event.history = merge_histories(
            db_event.history or [],
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": "remote-update",
                "description": "Änderungen aus CalDAV übernommen",
            },
        )
        db_event.updated_at = datetime.utcnow()
        session.add(db_event)
    logger.info("Updated local event %s from CalDAV changes", event.uid)


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


def mark_as_cancelled(results: Dict[int, tuple[bool, Optional[RemoteEventState]]]) -> None:
    """Update cancellation attempts with a history entry and timestamp."""
    with session_scope() as session:
        for event_id, (applied, remote_state) in results.items():
            event = session.get(TrackedEvent, event_id)
            if event is None:
                continue
            event.status = EventStatus.CANCELLED
            event.last_synced = datetime.utcnow()
            event.synced_version = event.local_version or 0
            event.sync_conflict = False
            event.sync_conflict_reason = None
            event.sync_conflict_snapshot = None
            event.last_modified_source = "local"
            if event.local_last_modified is None:
                event.local_last_modified = datetime.utcnow()
            if remote_state is not None:
                event.caldav_etag = remote_state.etag
                event.remote_last_modified = remote_state.last_modified
            description = (
                "Kalendereintrag als abgesagt markiert"
                if applied
                else "Kalendereintrag konnte nicht als abgesagt markiert werden"
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
            db_event.synced_version = db_event.local_version or 0
            db_event.sync_conflict = False
            db_event.sync_conflict_reason = None
            db_event.sync_conflict_snapshot = None
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
