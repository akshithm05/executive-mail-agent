"""Attachment repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.attachment import Attachment
from app.infra.repositories.base import SoftDeleteRepository


class AttachmentRepository(SoftDeleteRepository[Attachment]):
    """Persistence operations for email attachments."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Attachment)

    async def list_by_email(self, email_id: uuid.UUID) -> Sequence[Attachment]:
        """Return all attachments for a given email."""
        stmt = select(Attachment).where(
            Attachment.email_id == email_id, Attachment.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
