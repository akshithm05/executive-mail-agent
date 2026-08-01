"""Quiet-hours request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict


class QuietHoursUpdate(BaseModel):
    """Fields to create or update (upsert) a user's quiet-hours configuration."""

    is_enabled: bool = False
    start_time: time = time(22, 0)
    end_time: time = time(7, 0)
    timezone: str = "UTC"
    allow_urgent_override: bool = True


class QuietHoursRead(BaseModel):
    """Full quiet-hours representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_enabled: bool
    start_time: time
    end_time: time
    timezone: str
    allow_urgent_override: bool
    created_at: datetime
    updated_at: datetime
