"""PromptLog CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.infra.models.prompt_log import PromptLog
from app.infra.repositories.prompt_log import PromptLogRepository
from app.services.crud import CRUDService


class PromptLogService(CRUDService[PromptLog]):
    """CRUD operations for LLM prompt/response logs."""

    def __init__(self, repository: PromptLogRepository) -> None:
        super().__init__(repository)
        self._repo: PromptLogRepository = repository

    async def list_by_ai_history(self, ai_history_id: uuid.UUID) -> Sequence[PromptLog]:
        """Return all prompt logs backing a given AI history entry."""
        return await self._repo.list_by_ai_history(ai_history_id)
