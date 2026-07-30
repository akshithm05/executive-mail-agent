"""Memory request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryType = Literal[
    "fact",
    "preference_inference",
    "relationship",
    "context",
    "important_sender",
    "favorite_label",
    "archive_behavior",
    "reply_style",
    "priority_rule",
    "typical_deadline",
    "communication_preference",
]


class MemoryCreate(BaseModel):
    """Fields required to create a memory entry."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    source_email_id: uuid.UUID | None = None
    memory_type: MemoryType = "fact"
    memory_key: str | None = None
    content: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    is_pinned: bool = False


class MemoryUpdate(BaseModel):
    """Mutable fields on a memory entry; omitted fields are left unchanged."""

    content: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    importance_score: float | None = Field(default=None, ge=0, le=1)
    is_pinned: bool | None = None


class MemoryRead(BaseModel):
    """Full memory representation returned by the API.

    Deliberately omits the raw ``embedding`` vector -- callers only need to
    know one exists (``has_embedding``), not its values.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    source_email_id: uuid.UUID | None
    memory_type: str
    memory_key: str | None
    content: str
    confidence: float
    importance_score: float
    access_count: int
    reinforcement_count: int
    last_accessed_at: datetime | None
    is_pinned: bool
    embedding_model: str | None
    extra_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @property
    def has_embedding(self) -> bool:
        """Whether this memory has an embedding computed (semantic-searchable)."""
        return self.embedding_model is not None
