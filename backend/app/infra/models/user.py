"""User ORM model.

A ``User`` is a person who has signed in with Google. Every user belongs to a
``Tenant`` (Phase 1's root aggregate); a personal tenant is auto-provisioned on
first login so the multi-tenant seam stays exercised without requiring an
invite/org-creation flow yet.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A person authenticated via Google OAuth."""

    __tablename__ = "users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    google_subject: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    picture_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<User id={self.id!s} email={self.email!r}>"
