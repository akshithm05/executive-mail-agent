"""FailedJob (retry queue / dead-letter queue) response schema."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class FailedJobRead(BaseModel):
    """A retry-queue / dead-letter-queue entry, as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    job_type: str
    payload: dict[str, Any]
    error_message: str
    attempt_count: int
    max_attempts: int
    status: str
    next_attempt_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
