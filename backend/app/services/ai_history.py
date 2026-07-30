"""AIHistory CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.infra.models.ai_history import AIHistory
from app.infra.repositories.ai_history import AIHistoryRepository
from app.services.crud import CRUDService


class AIHistoryService(CRUDService[AIHistory]):
    """CRUD operations for AI action history."""

    def __init__(self, repository: AIHistoryRepository) -> None:
        super().__init__(repository)
        self._repo: AIHistoryRepository = repository

    async def list_by_user(
        self, user_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[AIHistory]:
        """Return a user's AI history, most recent first."""
        return await self._repo.list_by_user(user_id, limit=limit, offset=offset)
