"""Push-device request/response schemas.

``PushDeviceRead`` never includes the token/subscription -- see the module
docstring on ``app/schemas/notification_channel.py`` for the same rationale.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PushDeviceRegister(BaseModel):
    """Fields required to register a new push device."""

    platform: str = Field(max_length=16)
    config: dict[str, Any] = Field(default_factory=dict)


class PushDeviceRead(BaseModel):
    """A push device's metadata -- never the underlying token/subscription."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: str
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
