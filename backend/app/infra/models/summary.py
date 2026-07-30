"""Summary ORM model."""

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
    from app.infra.models.email import Email

SUMMARY_TYPES = ("email", "thread", "daily_digest")


class Summary(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """An AI-generated summary of an email, thread, or daily digest."""

    __tablename__ = "summaries"
    __table_args__ = (
        Index("ix_summaries_user_id_created_at", "user_id", "created_at"),
        Index("ix_summaries_email_id", "email_id"),
        CheckConstraint(
            f"summary_type IN {SUMMARY_TYPES}", name="ck_summaries_summary_type"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: thread- and digest-level summaries aren't tied to one Email row.
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=True
    )
    gmail_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="email"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    email: Mapped[Email | None] = relationship(back_populates="summaries")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Summary id={self.id!s} summary_type={self.summary_type!r}>"
