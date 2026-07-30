"""Typed views over Google OAuth and Gmail API payloads.

Keeping these as plain, immutable dataclasses (rather than passing raw
``dict`` responses around) means the rest of the application never touches
Google's wire format directly -- only :mod:`app.infra.google.oauth_client`,
:mod:`app.infra.google.gmail_client`, and :mod:`app.infra.google.mime_parser`
know what the JSON looks like.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class GoogleTokenResponse:
    """Result of a token exchange or refresh call to Google's token endpoint."""

    access_token: str
    expires_in: int
    scope: str
    token_type: str
    refresh_token: str | None = None
    id_token: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleUserInfo:
    """The authenticated user's Google identity (OpenID Connect userinfo)."""

    sub: str
    email: str
    email_verified: bool
    name: str
    picture: str


@dataclass(frozen=True, slots=True)
class GmailProfile:
    """Response of ``users.getProfile``."""

    email_address: str
    messages_total: int
    threads_total: int
    history_id: str


@dataclass(frozen=True, slots=True)
class GmailLabel:
    """A Gmail label (system or user-created)."""

    id: str
    name: str
    type: str
    message_list_visibility: str | None = None
    label_list_visibility: str | None = None


@dataclass(frozen=True, slots=True)
class EmailAttachmentMeta:
    """Metadata for one attachment on a message, without its bytes."""

    attachment_id: str
    filename: str
    mime_type: str
    size: int


@dataclass(frozen=True, slots=True)
class ParsedEmail:
    """A Gmail message with headers and body decoded for consumption."""

    id: str
    thread_id: str
    label_ids: list[str]
    snippet: str
    subject: str
    from_address: str
    to_address: str
    cc_address: str
    date: str
    text_plain: str | None
    text_html: str | None
    attachments: list[EmailAttachmentMeta] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EmailAttachment:
    """A downloaded attachment's raw bytes plus its metadata."""

    attachment_id: str
    filename: str
    mime_type: str
    size: int
    data: bytes


@dataclass(frozen=True, slots=True)
class MessageSummary:
    """One row in a ``messages.list`` / search result page."""

    id: str
    thread_id: str


@dataclass(frozen=True, slots=True)
class MessagesPage:
    """A page of message search results."""

    messages: list[MessageSummary]
    next_page_token: str | None
    result_size_estimate: int


@dataclass(frozen=True, slots=True)
class GoogleCalendarEvent:
    """A Google Calendar event (``events.insert``/``get``/``update`` response)."""

    id: str
    status: str
    summary: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    html_link: str | None = None


@dataclass(frozen=True, slots=True)
class StoredCredential:
    """Decrypted, in-memory view of a user's Google OAuth credential.

    Never persisted or logged as-is; constructed only for the duration of a
    request from the decrypted database row.
    """

    user_id: str
    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    scope: str
