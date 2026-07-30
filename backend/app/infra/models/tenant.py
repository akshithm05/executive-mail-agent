"""Tenant ORM model.

The system is multi-tenant from day one (see the SDD). ``Tenant`` is the root
aggregate that later phases (users, mailboxes, drafts) hang off. It is included
in Phase 1 so the migration tooling and repository pattern have a real,
non-trivial table to exercise end to end.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An organization or individual account that owns users and mailboxes."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Tenant id={self.id!s} slug={self.slug!r} plan={self.plan!r}>"
