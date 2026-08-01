"""Denormalize the latest triage verdict onto ``emails``.

Revision ID: 0008_email_triage_fields
Revises: 0007_scheduling_sync
Create Date: 2026-07-31 00:00:00.000000

``category``/``priority_score``/``has_deadline``/``deadline_at`` already
exist per-run in ``ai_history.extra_metadata`` (JSON), but the Phase 9
dashboard (inbox summary, urgent-email list, priority heatmap, category
chart, deadlines list) needs to filter and sort on them in SQL. Rather than
querying/parsing JSON on every dashboard request, the triage graph's latest
verdict is now also written onto the ``Email`` row itself (see
``app/agents/email_agent.py``) -- ``ai_history`` remains the full audit
trail; these columns are a queryable cache of its most recent result.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_email_triage_fields"
down_revision: str | None = "0007_scheduling_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add denormalized category/priority/deadline columns to ``emails``."""
    op.add_column(
        "emails", sa.Column("category", sa.String(length=32), nullable=True)
    )
    op.add_column("emails", sa.Column("priority_score", sa.Float(), nullable=True))
    op.add_column(
        "emails",
        sa.Column(
            "has_deadline", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("emails", sa.Column("deadline_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_emails_user_id_category", "emails", ["user_id", "category"]
    )
    op.create_index(
        "ix_emails_user_id_priority_score", "emails", ["user_id", "priority_score"]
    )


def downgrade() -> None:
    """Remove the denormalized triage columns from ``emails``."""
    op.drop_index("ix_emails_user_id_priority_score", table_name="emails")
    op.drop_index("ix_emails_user_id_category", table_name="emails")
    op.drop_column("emails", "deadline_at")
    op.drop_column("emails", "has_deadline")
    op.drop_column("emails", "priority_score")
    op.drop_column("emails", "category")
