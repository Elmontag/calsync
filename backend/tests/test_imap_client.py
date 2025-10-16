"""Tests for IMAP calendar candidate helpers."""
from __future__ import annotations

from backend.app.services import imap_client


def test_is_calendar_attachment_supports_vcs_extension() -> None:
    """Mail parts with .vcs attachments should be processed as calendar files."""

    assert imap_client._is_calendar_attachment("application/octet-stream", "invite.VCS")


def test_is_calendar_attachment_supports_vcalendar_mime() -> None:
    """Calendar specific MIME types should be accepted even without a filename."""

    assert imap_client._is_calendar_attachment("text/x-vcalendar", None)


def test_extract_calendar_links_supports_vcs_urls() -> None:
    """Calendar links ending in .vcs should be recognised during scanning."""

    links = imap_client.extract_calendar_links("Termin: https://example.com/invite.vcs")
    assert links == ["https://example.com/invite.vcs"]
