"""Label ORM models: ``Label`` and the ``EmailLabel`` association.

``Label`` mirrors a Gmail label (system or user-created) per mailbox.
``EmailLabel`` is the many-to-many join between emails and labels, modeled
as an explicit association object (rather than a bare ``secondary=`` table)
because it carries its own timestamp -- when a label was applied.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
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


class Label(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """A mailbox label -- either synced from Gmail or created internally."""

    __tablename__ = "labels"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_labels_user_id_name"),
        Index("ix_labels_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_label_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)

    email_labels: Mapped[list[EmailLabel]] = relationship(
        back_populates="label", cascade="all, delete-orphan"
    )
    emails: Mapped[list[Email]] = relationship(
        secondary="email_labels", back_populates="labels", viewonly=True
    )

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Label id={self.id!s} name={self.name!r}>"


class EmailLabel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Association row: one label applied to one email.

    Deliberately has no :class:`~app.infra.db.mixins.SoftDeleteMixin`: this
    row represents *current* label assignment, not a historical record, so
    removing a label from an email hard-deletes the association row. The
    ``Email`` and ``Label`` rows themselves are unaffected and remain
    independently soft-deletable.
    """

    __tablename__ = "email_labels"
    __table_args__ = (
        UniqueConstraint(
            "email_id", "label_id", name="uq_email_labels_email_id_label_id"
        ),
        Index("ix_email_labels_label_id", "label_id"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    label_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), nullable=False
    )

    email: Mapped[Email] = relationship(back_populates="email_labels")
    label: Mapped[Label] = relationship(back_populates="email_labels")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<EmailLabel email_id={self.email_id!s} label_id={self.label_id!s}>"
