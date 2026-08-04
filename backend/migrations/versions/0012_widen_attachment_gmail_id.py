"""Widen attachments.gmail_attachment_id from VARCHAR(255) to TEXT.

Real Gmail attachment ids are opaque, server-generated tokens that can run
well past 255 characters -- the bounded column rejected real-world
attachments (StringDataRightTruncationError) that the short fake ids used
in tests never exposed.

Revision ID: 0012_widen_attachment_gmail_id
Revises: 0011_email_search
Create Date: 2026-08-02 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_widen_attachment_gmail_id"
down_revision: str | None = "0011_email_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen ``attachments.gmail_attachment_id`` to unbounded ``TEXT``."""
    op.alter_column(
        "attachments",
        "gmail_attachment_id",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Narrow ``attachments.gmail_attachment_id`` back to ``VARCHAR(255)``.

    Lossy if any stored id is already longer than 255 characters -- the
    scenario this migration exists to fix in the first place.
    """
    op.alter_column(
        "attachments",
        "gmail_attachment_id",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
