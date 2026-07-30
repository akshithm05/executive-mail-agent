"""Attachment CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.infra.models.attachment import Attachment
from app.infra.repositories.attachment import AttachmentRepository
from app.services.crud import CRUDService


class AttachmentService(CRUDService[Attachment]):
    """CRUD operations for attachment metadata."""

    def __init__(self, repository: AttachmentRepository) -> None:
        super().__init__(repository)
        self._repo: AttachmentRepository = repository

    async def list_by_email(self, email_id: uuid.UUID) -> Sequence[Attachment]:
        """Return all attachments for a given email."""
        return await self._repo.list_by_email(email_id)
