"""CalendarEvent CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from app.infra.models.calendar_event import CalendarEvent
from app.infra.repositories.calendar_event import CalendarEventRepository
from app.services.crud import CRUDService


class CalendarEventService(CRUDService[CalendarEvent]):
    """CRUD operations for calendar events."""

    def __init__(self, repository: CalendarEventRepository) -> None:
        super().__init__(repository)
        self._repo: CalendarEventRepository = repository

    async def list_in_range(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[CalendarEvent]:
        """Return events for a user starting within ``[start, end)``."""
        return await self._repo.list_in_range(user_id, start, end)
