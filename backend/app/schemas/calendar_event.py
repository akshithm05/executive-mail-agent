"""CalendarEvent request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CalendarEventStatus = Literal["confirmed", "tentative", "cancelled"]


class CalendarEventCreate(BaseModel):
    """Fields required to create a calendar event."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None = None
    google_event_id: str | None = Field(default=None, max_length=255)
    title: str = Field(max_length=500)
    description: str | None = None
    location: str | None = Field(default=None, max_length=500)
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    status: CalendarEventStatus = "confirmed"
    attendees: list[Any] = Field(default_factory=list)


class CalendarEventUpdate(BaseModel):
    """Mutable fields on a calendar event; omitted fields are left unchanged."""

    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: CalendarEventStatus | None = None
    attendees: list[Any] | None = None


class CalendarEventRead(BaseModel):
    """Full calendar event representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID | None
    google_event_id: str | None
    title: str
    description: str | None
    location: str | None
    start_at: datetime
    end_at: datetime
    all_day: bool
    status: str
    attendees: list[Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
