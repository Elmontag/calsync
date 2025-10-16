"""Utility helpers for working with IMAP mailboxes."""
from __future__ import annotations

import email
import logging
import os
from dataclasses import dataclass
from email.message import Message
from typing import Callable, Iterable, List, Optional, Sequence

from imapclient import IMAPClient

logger = logging.getLogger(__name__)


def _load_default_timeout() -> int:
    """Determine the default IMAP socket timeout in seconds.

    Operators can override the timeout via the ``IMAP_CLIENT_TIMEOUT``
    environment variable.  Invalid overrides fall back to a conservative
    default while logging a warning for better visibility.
    """

    raw_value = os.getenv("IMAP_CLIENT_TIMEOUT", "180")
    try:
        parsed = int(raw_value)
        if parsed <= 0:
            raise ValueError
        return parsed
    except ValueError:
        logger.warning(
            "Ungültiger Wert für IMAP_CLIENT_TIMEOUT (%s), verwende 180 Sekunden.",
            raw_value,
        )
        return 180


DEFAULT_IMAP_CLIENT_TIMEOUT = _load_default_timeout()


@dataclass
class ImapSettings:
    host: str
    username: str
    password: str
    ssl: bool = True
    port: Optional[int] = None
    timeout: Optional[int] = None


@dataclass
class MailAttachment:
    filename: str
    content_type: str
    payload: bytes


@dataclass
class CalendarCandidate:
    message_id: str
    subject: str
    sender: str
    folder: str
    attachments: List[MailAttachment]
    links: List[str]


@dataclass
class FolderSelection:
    name: str
    include_subfolders: bool = True


CALENDAR_MIME_TYPES = {"text/calendar", "text/x-vcalendar"}
CALENDAR_EXTENSIONS = (".ics", ".vcs")


def _is_calendar_attachment(content_type: str, filename: Optional[str]) -> bool:
    """Return True when the mail part represents a calendar payload."""

    if content_type in CALENDAR_MIME_TYPES:
        return True
    if filename:
        lowered = filename.lower()
        return any(lowered.endswith(ext) for ext in CALENDAR_EXTENSIONS)
    return False


def delete_message(settings: ImapSettings, folder: str, message_id: str) -> bool:
    """Remove a message from the given folder by UID or Message-ID.

    Returns ``True`` when the message was deleted (or already absent) and
    ``False`` when no matching message could be located.
    """

    with ImapConnection(settings) as client:
        logger.info("Deleting IMAP message %s from %s", message_id, folder)
        client.select_folder(folder)

        # Prefer using the numeric UID as it is stable for most servers.
        try:
            uid = int(message_id)
        except (TypeError, ValueError):
            uid = None

        if uid is not None:
            matches = client.search(["UID", str(uid)], uid=True)
        else:
            # Fall back to a Message-ID search when the identifier is not numeric.
            matches = client.search(["HEADER", "Message-ID", message_id], uid=True)

        if not matches:
            logger.warning(
                "Keine Nachricht %s in Ordner %s gefunden", message_id, folder
            )
            return False

        client.delete_messages(matches, uid=True)
        client.expunge()
        return True


class ImapConnection:
    """Context manager for IMAP operations."""

    def __init__(self, settings: ImapSettings):
        self.settings = settings
        self._client: Optional[IMAPClient] = None

    def __enter__(self) -> IMAPClient:
        timeout = (
            self.settings.timeout
            if self.settings.timeout is not None
            else DEFAULT_IMAP_CLIENT_TIMEOUT
        )
        logger.debug(
            "Opening IMAP connection to %s (Timeout: %ss)",
            self.settings.host,
            timeout,
        )
        self._client = IMAPClient(
            host=self.settings.host,
            port=self.settings.port,
            ssl=self.settings.ssl,
            timeout=timeout,
        )
        self._client.login(self.settings.username, self.settings.password)
        return self._client

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client is not None:
            logger.debug("Closing IMAP connection")
            try:
                self._client.logout()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.exception("Failed to close IMAP connection cleanly")


def fetch_calendar_candidates(
    settings: ImapSettings,
    folders: Iterable[FolderSelection | str],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[CalendarCandidate]:
    """Collect calendar candidates from the configured folders."""
    candidates: List[CalendarCandidate] = []

    with ImapConnection(settings) as client:
        available = client.list_folders()
        for folder_name in _expand_folders(folders, available):
            logger.info("Scanning IMAP folder %s", folder_name)
            try:
                client.select_folder(folder_name)
            except Exception:
                logger.exception("Konnte IMAP Ordner %s nicht öffnen", folder_name)
                continue
            message_ids = client.search("ALL")
            if not message_ids:
                logger.debug("No messages found in folder %s", folder_name)
                continue
            if progress_callback is not None:
                progress_callback(0, len(message_ids))
            for uid, message_data in client.fetch(message_ids, ["RFC822"]).items():
                raw_message: bytes = message_data[b"RFC822"]
                message: Message = email.message_from_bytes(raw_message)
                attachments: List[MailAttachment] = []
                links: List[str] = []
                for part in message.walk():
                    content_type = part.get_content_type()
                    filename = part.get_filename()
                    is_calendar_part = _is_calendar_attachment(content_type, filename)
                    if is_calendar_part:
                        payload = part.get_payload(decode=True) or b""
                        if filename:
                            attachment_name = filename
                        else:
                            default_extension = ".vcs" if content_type == "text/x-vcalendar" else ".ics"
                            attachment_name = f"calendar{default_extension}"
                        attachments.append(
                            MailAttachment(
                                filename=attachment_name,
                                content_type=content_type,
                                payload=payload,
                            )
                        )
                    if content_type == "text/plain":
                        payload_text = part.get_payload(decode=True) or b""
                        links.extend(extract_calendar_links(payload_text.decode(errors="ignore")))
                if progress_callback is not None:
                    progress_callback(1, 0)
                candidates.append(
                    CalendarCandidate(
                        message_id=str(uid),
                        subject=message.get("Subject", "(no subject)"),
                        sender=message.get("From", "unknown"),
                        folder=folder_name,
                        attachments=attachments,
                        links=links,
                    )
                )
    return candidates


def _expand_folders(
    folders: Iterable[FolderSelection | str],
    available: Sequence[tuple[Sequence[str], str, str]],
) -> List[str]:
    """Resolve folder selections into a concrete list of mailbox folders."""

    normalized: List[FolderSelection] = []
    for entry in folders:
        if isinstance(entry, FolderSelection):
            normalized.append(entry)
        else:
            normalized.append(FolderSelection(name=entry))

    available_names = [(delim or "/", name) for _, delim, name in available]
    resolved: List[str] = []
    seen = set()

    for selection in normalized:
        base = selection.name
        if base not in seen:
            resolved.append(base)
            seen.add(base)
        if not selection.include_subfolders:
            continue
        matched_subfolders = False
        for delim, candidate in available_names:
            if candidate == base:
                matched_subfolders = True
                continue
            prefix = f"{base}{delim}"
            if candidate.startswith(prefix) and candidate not in seen:
                resolved.append(candidate)
                seen.add(candidate)
                matched_subfolders = True
        if not matched_subfolders and base not in {name for _, _, name in available}:
            logger.warning("IMAP Ordner %s wurde nicht gefunden", base)
    return resolved


def extract_calendar_links(text: str) -> List[str]:
    """Extract potential calendar links from plain text bodies."""
    import re

    link_pattern = re.compile(r"https?://\S+(?:/download/(?:ics|vcs)|\.(?:ics|vcs)\b)")
    links = link_pattern.findall(text)
    logger.debug("Found %s calendar links", len(links))
    return links
