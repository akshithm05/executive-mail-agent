"""Summary CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.infra.models.summary import Summary
from app.infra.repositories.summary import SummaryRepository
from app.services.crud import CRUDService


class SummaryService(CRUDService[Summary]):
    """CRUD operations for AI-generated summaries."""

    def __init__(self, repository: SummaryRepository) -> None:
        super().__init__(repository)
        self._repo: SummaryRepository = repository

    async def list_by_email(self, email_id: uuid.UUID) -> Sequence[Summary]:
        """Return all summaries generated for a given email."""
        return await self._repo.list_by_email(email_id)
