"""Extend draft_replies for the Draft Reply Engine (subject, tone, reasoning).

Revision ID: 0006_draft_reply_engine
Revises: 0005_memory_long_term
Create Date: 2026-07-30 02:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_draft_reply_engine"
down_revision: str | None = "0005_memory_long_term"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REPLY_TONES = (
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


def upgrade() -> None:
    """Add subject/tone/reasoning/confidence columns to ``draft_replies``.

    ``subject`` existed nowhere before this -- the reply_draft graph node
    already generated one, but ``database_update`` silently dropped it when
    persisting. Backfilling existing rows to "" is safe since no code path
    that reads ``subject`` existed prior to this migration either.
    """
    op.add_column(
        "draft_replies",
        sa.Column("subject", sa.String(length=998), nullable=False, server_default=""),
    )
    op.add_column("draft_replies", sa.Column("tone", sa.String(length=32), nullable=True))
    op.add_column("draft_replies", sa.Column("reasoning", sa.Text(), nullable=True))
    op.add_column("draft_replies", sa.Column("confidence", sa.Float(), nullable=True))

    op.create_check_constraint(
        "ck_draft_replies_tone",
        "draft_replies",
        f"tone IS NULL OR tone IN {_REPLY_TONES}",
    )


def downgrade() -> None:
    """Reverse the Draft Reply Engine column additions."""
    op.drop_constraint("ck_draft_replies_tone", "draft_replies", type_="check")
    op.drop_column("draft_replies", "confidence")
    op.drop_column("draft_replies", "reasoning")
    op.drop_column("draft_replies", "tone")
    op.drop_column("draft_replies", "subject")
