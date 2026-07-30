"""Add soft delete to users.

Revision ID: 0004_users_soft_delete
Revises: 0003_domain_models
Create Date: 2026-07-30 00:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_users_soft_delete"
down_revision: str | None = "0003_domain_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the ``deleted_at`` column to ``users`` for schema-wide consistency.

    Note: no code path in this codebase currently soft-deletes a user (there
    is no account-deletion flow yet). ``UserRepository`` extends
    ``SoftDeleteRepository`` and excludes soft-deleted rows from lookups, but
    ``google_subject``/``email`` remain uniquely constrained -- a future
    account-deletion feature will need to decide whether re-signup after
    deletion reactivates the row or requires releasing the unique columns.
    """
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])


def downgrade() -> None:
    """Remove the ``deleted_at`` column from ``users``."""
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_at")
