"""DraftReply ORM model.

The Draft Reply Engine (see ``app/agents/graph.py``'s ``reply_draft`` node
and ``app/api/v1/routes/draft_replies.py``) only ever produces or edits rows
in this table -- there is no code path anywhere in this codebase that sends
an email or creates a Gmail draft from one. ``status`` progresses at most to
``"approved"``/``"sent"`` as bookkeeping for a human-driven send that would
happen through some future, explicitly separate integration; reaching
``"sent"`` here never triggers an outbound send by itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base
from app.infra.db.mixins import (
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.infra.models.email import Email

STATUSES = ("draft", "pending_review", "approved", "sent", "discarded")
GENERATED_BY_VALUES = ("ai", "user")
REPLY_TONES = (
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
)


class DraftReply(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """An AI-generated or user-authored draft reply to an email."""

    __tablename__ = "draft_replies"
    __table_args__ = (
        Index("ix_draft_replies_email_id", "email_id"),
        Index("ix_draft_replies_user_id_status", "user_id", "status"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_draft_replies_status"),
        CheckConstraint(
            f"generated_by IN {GENERATED_BY_VALUES}",
            name="ck_draft_replies_generated_by",
        ),
        CheckConstraint(
            f"tone IS NULL OR tone IN {REPLY_TONES}", name="ck_draft_replies_tone"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # CASCADE, unlike Task/CalendarEvent: a draft reply is meaningless
    # without the email it replies to.
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    generated_by: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    # The tone the Draft Reply Engine chose (or was asked to use on
    # regeneration). Null for drafts authored directly by a user, who has no
    # need to classify their own tone.
    tone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    gmail_draft_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)

    email: Mapped[Email] = relationship(back_populates="draft_replies")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<DraftReply id={self.id!s} status={self.status!r}>"
