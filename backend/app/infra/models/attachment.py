"""Attachment ORM model.

Attachment *metadata* only -- the raw bytes are not stored in Postgres.
``storage_uri`` points at wherever the blob actually lives (object storage);
downloading the bytes still goes through the Gmail API
(``GmailClient.get_attachment``) until/unless a later phase adds a blob
cache.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
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


class Attachment(
    UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base
):
    """Metadata for one attachment on an :class:`~app.infra.models.email.Email`."""

    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint(
            "email_id",
            "gmail_attachment_id",
            name="uq_attachments_email_id_gmail_attachment_id",
        ),
        Index("ix_attachments_email_id", "email_id"),
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False
    )
    # Text, not a bounded VARCHAR: Gmail's real attachment ids are opaque,
    # server-generated tokens that can run well past 255 characters --
    # unlike the short fake ids used in tests, which never exposed this.
    gmail_attachment_id: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    storage_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    email: Mapped[Email] = relationship(back_populates="attachments")

    def __repr__(self) -> str:
        """Return an unambiguous representation for logs and debugging."""
        return f"<Attachment id={self.id!s} filename={self.filename!r}>"
