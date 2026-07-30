"""AuditLog request/response schemas.

No update schema: audit log entries are immutable once recorded (see
``app/services/audit_log.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogCreate(BaseModel):
    """Fields required to record an audit log entry."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    action: str = Field(max_length=128)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: uuid.UUID | None = None
    ip_address: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)
    extra_metadata: dict[str, Any] | None = None


class AuditLogRead(BaseModel):
    """Full audit log entry representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    ip_address: str | None
    user_agent: str | None
    extra_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
