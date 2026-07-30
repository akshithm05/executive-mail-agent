"""DraftReply request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DraftReplyStatus = Literal["draft", "pending_review", "approved", "sent", "discarded"]
DraftReplyGeneratedBy = Literal["ai", "user"]
DraftReplyTone = Literal[
    "professional",
    "friendly",
    "formal",
    "executive",
    "short",
    "detailed",
    "apology",
    "thank_you",
    "follow_up",
    "negotiation",
    "clarification",
]


class DraftReplyCreate(BaseModel):
    """Fields required to create a draft reply."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID
    subject: str = Field(default="", max_length=998)
    body_text: str
    body_html: str | None = None
    status: DraftReplyStatus = "draft"
    generated_by: DraftReplyGeneratedBy = "ai"
    tone: DraftReplyTone | None = None
    reasoning: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class DraftReplyEdit(BaseModel):
    """User-editable fields on a draft reply.

    Deliberately excludes ``status``, ``tone``, ``confidence``, and
    ``gmail_draft_id`` -- editing the wording of a draft is not the same
    action as approving, discarding, or regenerating it (see the dedicated
    routes for those), and a human hand-edit invalidates the AI's own
    confidence/tone self-assessment rather than leaving it misleadingly
    attached to text the AI didn't actually write.
    """

    subject: str | None = Field(default=None, max_length=998)
    body_text: str | None = None
    body_html: str | None = None


class DraftReplyRegenerateRequest(BaseModel):
    """Optional tone override for on-demand draft regeneration."""

    tone: DraftReplyTone | None = Field(
        default=None,
        description="Force this tone instead of letting the model infer one.",
    )


class DraftReplyUpdate(BaseModel):
    """Mutable fields on a draft reply; omitted fields are left unchanged."""

    subject: str | None = Field(default=None, max_length=998)
    body_text: str | None = None
    body_html: str | None = None
    status: DraftReplyStatus | None = None
    gmail_draft_id: str | None = Field(default=None, max_length=255)


class DraftReplyRead(BaseModel):
    """Full draft reply representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    email_id: uuid.UUID
    subject: str
    body_text: str
    body_html: str | None
    status: str
    generated_by: str
    tone: str | None
    reasoning: str | None
    confidence: float | None
    gmail_draft_id: str | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
