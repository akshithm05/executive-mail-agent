"""Email ORM model.

An ``Email`` is a Gmail message mirrored locally so the AI pipeline (triage,
drafting, summarization) can query and relate it to tasks, calendar events,
draft replies, and labels without round-tripping to the Gmail API on every
read.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text, UniqueConstraint
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
    from app.infra.models.attachment import Attachment
    from app.infra.models.calendar_event import CalendarEvent
    from app.infra.models.draft_reply import DraftReply
    from app.infra.models.label import EmailLabel, Label
    from app.infra.models.memory import Memory
    from app.infra.models.summary import Summary
    from app.infra.models.task import Task


class Email(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A Gmail message mirrored locally for the AI pipeline."""

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "gmail_message_id", name="uq_emails_user_id_gmail_message_id"
        ),
        Index("ix_emails_user_id_received_at", "user_id", "received_at"),
        Index("ix_emails_user_id_gmail_thread_id", "user_id", "gmail_thread_id"),
        Index("ix_emails_user_id_category", "user_id", "category"),
        Index("ix_emails_user_id_priority_score", "user_id", "priority_score"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    snippet: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    to_addresses: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cc_addresses: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Denormalized cache of the triage graph's latest verdict (see
    # ``app/agents/graph.py``'s ``categorize``/``priority_score``/
    # ``deadline_detection`` nodes and ``app/agents/email_agent.py``, which
    # writes these back after each run) -- the full audit trail lives in
    # ``AIHistory.extra_metadata``; these columns exist so dashboard reads
    # can filter/sort in SQL instead of parsing JSON per row.
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    priority_score: Mapped[float | None] = mapped_column(nullable=True)
    has_deadline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deadline_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # -- Embedding (semantic search) -----------------------------------------
    # A plain JSON float array, mirroring ``Memory.embedding`` -- see that
    # model's docstring for why this isn't a ``pgvector`` column. Populated
    # asynchronously by the scheduled ``backfill_email_embeddings`` job (see
    # ``app/scheduler.py``), not at ingestion time, so Phase 4's ingestion
    # pipeline stays untouched; ``app/services/email_search.py`` treats a
    # null embedding as "no semantic score yet" rather than an error.
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )
    email_labels: Mapped[list[EmailLabel]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )
    labels: Mapped[list[Label]] = relationship(
        secondary="email_labels", back_populates="emails", viewonly=True
    )
    # These four are all SET NULL / independently soft-deletable relations,
    # so no cascade delete-orphan: removing an email must not silently
    # delete the tasks, events, summaries, or memories derived from it.
    tasks: Mapped[list[Task]] = relationship(back_populates="email")
    calendar_events: Mapped[list[CalendarEvent]] = relationship(back_populates="email")
    ai_history_entries: Mapped[list[AIHistory]] = relationship(back_populates="email")
    summaries: Mapped[list[Summary]] = relationship(back_populates="email")
    memories: Mapped[list[Memory]] = relationship(back_populates="source_email")
    # DraftReply IS cascade-deleted with its email (see draft_reply.py).
    draft_replies: Mapped[list[DraftReply]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Email id={self.id!s} gmail_message_id={self.gmail_message_id!r}>"
