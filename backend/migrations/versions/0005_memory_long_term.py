"""Extend memories for the long-term memory subsystem.

Revision ID: 0005_memory_long_term
Revises: 0004_users_soft_delete
Create Date: 2026-07-30 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_memory_long_term"
down_revision: str | None = "0004_users_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_MEMORY_TYPES = (
    "fact",
    "preference_inference",
    "relationship",
    "context",
)
_NEW_MEMORY_TYPES = (
    *_OLD_MEMORY_TYPES,
    "important_sender",
    "favorite_label",
    "archive_behavior",
    "reply_style",
    "priority_rule",
    "typical_deadline",
    "communication_preference",
)


def upgrade() -> None:
    """Add scoring, embedding, and dedupe-key columns to ``memories``.

    ``importance_score`` existed before as a nullable, write-only column;
    backfilling it to a non-null 0.5 default (neutral) makes it safe for the
    scoring function (``app/agents/memory_scoring.py``) to always read a
    real number rather than special-casing ``None``.
    """
    op.add_column(
        "memories", sa.Column("memory_key", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "memories",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.execute("UPDATE memories SET importance_score = 0.5 WHERE importance_score IS NULL")
    op.alter_column(
        "memories",
        "importance_score",
        existing_type=sa.Float(),
        nullable=False,
        server_default="0.5",
    )
    op.add_column(
        "memories",
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "memories",
        sa.Column(
            "reinforcement_count", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "memories", sa.Column("last_accessed_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "memories",
        sa.Column(
            "is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("memories", sa.Column("embedding", sa.JSON(), nullable=True))
    op.add_column(
        "memories", sa.Column("embedding_model", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "memories",
        sa.Column(
            "extra_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
    )

    op.create_index(
        "ix_memories_user_id_memory_type_memory_key",
        "memories",
        ["user_id", "memory_type", "memory_key"],
    )

    op.drop_constraint("ck_memories_memory_type", "memories", type_="check")
    op.create_check_constraint(
        "ck_memories_memory_type", "memories", f"memory_type IN {_NEW_MEMORY_TYPES}"
    )


def downgrade() -> None:
    """Reverse the long-term memory column additions."""
    op.drop_constraint("ck_memories_memory_type", "memories", type_="check")
    op.create_check_constraint(
        "ck_memories_memory_type", "memories", f"memory_type IN {_OLD_MEMORY_TYPES}"
    )

    op.drop_index("ix_memories_user_id_memory_type_memory_key", table_name="memories")

    op.drop_column("memories", "extra_metadata")
    op.drop_column("memories", "embedding_model")
    op.drop_column("memories", "embedding")
    op.drop_column("memories", "is_pinned")
    op.drop_column("memories", "last_accessed_at")
    op.drop_column("memories", "reinforcement_count")
    op.drop_column("memories", "access_count")
    op.alter_column(
        "memories",
        "importance_score",
        existing_type=sa.Float(),
        nullable=True,
        server_default=None,
    )
    op.drop_column("memories", "confidence")
    op.drop_column("memories", "memory_key")
