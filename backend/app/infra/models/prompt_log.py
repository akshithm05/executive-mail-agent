"""PromptLog ORM model.

Raw per-call LLM observability log (provider, model, prompt/response text,
token counts, latency) -- lower-level than
:class:`~app.infra.models.ai_history.AIHistory`, which one or more
``PromptLog`` rows may support.
"""

from __future__ import annotations

import uuid
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
    from app.infra.models.ai_history import AIHistory

STATUSES = ("success", "error")


class PromptLog(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A single LLM request/response pair, logged for observability."""

    __tablename__ = "prompt_logs"
    __table_args__ = (
        Index("ix_prompt_logs_created_at", "created_at"),
        Index("ix_prompt_logs_ai_history_id", "ai_history_id"),
        Index("ix_prompt_logs_user_id", "user_id"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_prompt_logs_status"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ai_history_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_history.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_history: Mapped[AIHistory | None] = relationship(back_populates="prompt_logs")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<PromptLog id={self.id!s} provider={self.provider!r}>"
