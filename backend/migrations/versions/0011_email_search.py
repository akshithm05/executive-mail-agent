"""AI-powered search: email embedding columns for semantic ranking.

Revision ID: 0011_email_search
Revises: 0010_notification_channels
Create Date: 2026-08-01 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_email_search"
down_revision: str | None = "0010_notification_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``embedding``/``embedding_model`` columns to ``emails``."""
    op.add_column("emails", sa.Column("embedding", sa.JSON(), nullable=True))
    op.add_column(
        "emails", sa.Column("embedding_model", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    """Drop the embedding columns from ``emails``."""
    op.drop_column("emails", "embedding_model")
    op.drop_column("emails", "embedding")
