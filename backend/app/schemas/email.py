"""Email request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmailCreate(BaseModel):
    """Fields required to create an email."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    gmail_message_id: str = Field(max_length=255)
    gmail_thread_id: str = Field(max_length=255)
    subject: str = Field(default="", max_length=998)
    snippet: str = Field(default="", max_length=1024)
    from_address: str = Field(max_length=320)
    to_addresses: str = ""
    cc_addresses: str = ""
    body_text: str | None = None
    body_html: str | None = None
    received_at: datetime


class EmailUpdate(BaseModel):
    """Mutable fields on an email; omitted fields are left unchanged."""

    is_read: bool | None = None
    is_starred: bool | None = None
    body_text: str | None = None
    body_html: str | None = None


class EmailRead(BaseModel):
    """Full email representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    gmail_message_id: str
    gmail_thread_id: str
    subject: str
    snippet: str
    from_address: str
    to_addresses: str
    cc_addresses: str
    body_text: str | None
    body_html: str | None
    received_at: datetime
    is_read: bool
    is_starred: bool
    category: str | None
    priority_score: float | None
    has_deadline: bool
    deadline_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class EmailSummaryRead(BaseModel):
    """Compact email representation for list views (inbox, urgent, deadlines).

    Omits ``body_text``/``body_html`` -- list views never need the full
    body, and leaving it out keeps these (frequently large) list responses
    small.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    snippet: str
    from_address: str
    received_at: datetime
    is_read: bool
    is_starred: bool
    category: str | None
    priority_score: float | None
    has_deadline: bool
    deadline_at: datetime | None
