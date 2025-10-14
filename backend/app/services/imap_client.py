"""Utility helpers for working with IMAP mailboxes."""
from __future__ import annotations

import email
import logging
from dataclasses import dataclass
from email.message import Message
from typing import Iterable, List, Optional

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
    folders: Iterable[str],
) -> List[CalendarCandidate]:
    """Collect calendar candidates from the configured folders."""
    candidates: List[CalendarCandidate] = []

    with ImapConnection(settings) as client:
        for folder in folders:
            logger.info("Scanning IMAP folder %s", folder)
            client.select_folder(folder)
            message_ids = client.search("ALL")
            if not message_ids:
                logger.debug("No messages found in folder %s", folder)
                continue
            for uid, message_data in client.fetch(message_ids, ["RFC822"]).items():
                raw_message: bytes = message_data[b"RFC822"]
                message: Message = email.message_from_bytes(raw_message)
                attachments: List[MailAttachment] = []
                links: List[str] = []
                for part in message.walk():
                    content_type = part.get_content_type()
                    filename = part.get_filename()
                    if filename and filename.lower().endswith(".ics"):
                        payload = part.get_payload(decode=True) or b""
                        attachments.append(
                            MailAttachment(
                                filename=filename,
                                content_type=content_type,
                                payload=payload,
                            )
                        )
                    if content_type == "text/plain":
                        payload_text = part.get_payload(decode=True) or b""
                        links.extend(extract_calendar_links(payload_text.decode(errors="ignore")))
                candidates.append(
                    CalendarCandidate(
                        message_id=str(uid),
                        subject=message.get("Subject", "(no subject)"),
                        sender=message.get("From", "unknown"),
                        folder=folder,
                        attachments=attachments,
                        links=links,
                    )
                )
    return candidates


def extract_calendar_links(text: str) -> List[str]:
    """Extract potential calendar links from plain text bodies."""
    import re

    link_pattern = re.compile(r"https?://\S+(?:/download/ics|\.ics\b)")
    links = link_pattern.findall(text)
    logger.debug("Found %s calendar links", len(links))
    return links
