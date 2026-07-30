"""AIHistory ORM model.

A higher-level, human-readable log of AI actions/decisions (e.g. "triaged
this email as urgent", "generated a draft reply"), distinct from the raw
per-call :class:`~app.infra.models.prompt_log.PromptLog` records it may be
composed of.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
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
    from app.infra.models.prompt_log import PromptLog
    from app.infra.models.task import Task


class AIHistory(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A record of one AI-driven action taken on behalf of a user."""

    __tablename__ = "ai_history"
    __table_args__ = (
        Index("ix_ai_history_user_id_created_at", "user_id", "created_at"),
        Index("ix_ai_history_email_id", "email_id"),
        Index("ix_ai_history_task_id", "task_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    email: Mapped[Email | None] = relationship(back_populates="ai_history_entries")
    task: Mapped[Task | None] = relationship(back_populates="ai_history_entries")
    prompt_logs: Mapped[list[PromptLog]] = relationship(back_populates="ai_history")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<AIHistory id={self.id!s} action_type={self.action_type!r}>"
