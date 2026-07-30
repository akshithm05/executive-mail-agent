"""Memory ORM model.

Long-term AI memory about a user (facts, inferred preferences, relationship
context) that persists across conversations/sessions. Beyond raw storage,
this model carries everything the long-term memory subsystem (see
``app/agents/memory_scoring.py``, ``app/agents/embeddings.py``, and
``app/services/memory.py``) needs to score, decay, retrieve, and summarize
memories over time:

* ``importance_score`` / ``confidence`` / ``access_count`` /
  ``reinforcement_count`` / ``last_accessed_at`` feed the composite scoring
  function that ranks memories at retrieval time and decays stale ones.
* ``memory_key`` lets a memory be looked up and reinforced (rather than
  duplicated) across multiple emails -- e.g. one row per important sender,
  keyed by their address, that gets more confident each time they email
  again, instead of a new row per email.
* ``embedding`` / ``embedding_model`` store a fixed-size vector for semantic
  similarity search. It is a plain JSON float array today (portable across
  SQLite tests and Postgres with no extension required) rather than a
  ``pgvector`` column -- see ``MemoryRepository.list_embedding_candidates``
  for the documented seam where a real vector database or the Postgres
  ``vector`` type can be swapped in later without touching call sites.
* ``is_pinned`` marks memories that should never decay or be summarized away
  (e.g. an explicit, user-confirmed communication preference).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
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

# "fact"/"preference_inference"/"relationship"/"context" are the original,
# general-purpose categories. The rest are the specific long-term-memory
# categories the assistant is expected to learn (see module docstring):
# important senders, favorite labels, archive behavior, reply style,
# priority rules, typical deadlines, and communication preferences.
MEMORY_TYPES = (
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
)


class Memory(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A single long-term memory entry the AI has stored about a user."""

    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_id_memory_type", "user_id", "memory_type"),
        Index("ix_memories_source_email_id", "source_email_id"),
        Index(
            "ix_memories_user_id_memory_type_memory_key",
            "user_id",
            "memory_type",
            "memory_key",
        ),
        CheckConstraint(
            f"memory_type IN {MEMORY_TYPES}", name="ck_memories_memory_type"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False, default="fact")
    # Stable dedupe/lookup key within (user_id, memory_type), e.g. a sender's
    # email address for "important_sender" or a label name for
    # "favorite_label". Null for one-off, non-reinforceable "fact" memories.
    memory_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # -- Scoring -------------------------------------------------------------
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.5)
    importance_score: Mapped[float] = mapped_column(nullable=False, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reinforcement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_accessed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # -- Embedding (semantic similarity search) ------------------------------
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    source_email: Mapped[Email | None] = relationship(back_populates="memories")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Memory id={self.id!s} memory_type={self.memory_type!r}>"
