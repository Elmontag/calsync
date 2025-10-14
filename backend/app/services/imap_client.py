"""Utility helpers for working with IMAP mailboxes."""
from __future__ import annotations

import email
import logging
from dataclasses import dataclass
from email.message import Message
from typing import Callable, Iterable, List, Optional, Sequence

from imapclient import IMAPClient

logger = logging.getLogger(__name__)


@dataclass
class ImapSettings:
    host: str
    username: str
    password: str
    ssl: bool = True
    port: Optional[int] = None


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


class ImapConnection:
    """Context manager for IMAP operations."""

    def __init__(self, settings: ImapSettings):
        self.settings = settings
        self._client: Optional[IMAPClient] = None

    def __enter__(self) -> IMAPClient:
        logger.debug("Opening IMAP connection to %s", self.settings.host)
        self._client = IMAPClient(
            host=self.settings.host,
            port=self.settings.port,
            ssl=self.settings.ssl,
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
                    is_calendar_part = content_type == "text/calendar" or (
                        filename and filename.lower().endswith(".ics")
                    )
                    if is_calendar_part:
                        payload = part.get_payload(decode=True) or b""
                        attachment_name = filename or "calendar.ics"
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

    link_pattern = re.compile(r"https?://\S+(?:/download/ics|\.ics\b)")
    links = link_pattern.findall(text)
    logger.debug("Found %s calendar links", len(links))
    return links
