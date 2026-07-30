"""Reusable ORM mixins.

These mixins provide the columns nearly every table needs (a UUID primary key
and created/updated timestamps) without repeating the declarations on every
model. Using :class:`sqlalchemy.Uuid` keeps the models dialect-agnostic so the
same models run on PostgreSQL in production and SQLite in tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    """Adds a client-generated UUID primary key named ``id``."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantScopedMixin:
    """Adds a ``tenant_id`` foreign key to the owning tenant.

    Nearly every domain table in this system is scoped to a tenant (the
    multi-tenant root aggregate, see ``app/infra/models/tenant.py``); this
    mixin keeps that column, its FK, and its index declaration in one place
    instead of repeating them on every model.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class SoftDeleteMixin:
    """Adds a ``deleted_at`` column implementing soft deletes.

    Rows are never physically removed by application code; ``deleted_at`` is
    set instead, and repositories built on
    :class:`~app.infra.repositories.base.SoftDeleteRepository` exclude
    soft-deleted rows from reads by default. Indexed because "active rows"
    queries always filter on it.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        nullable=True, default=None, index=True
    )

    @property
    def is_deleted(self) -> bool:
        """True if this row has been soft-deleted."""
        return self.deleted_at is not None
