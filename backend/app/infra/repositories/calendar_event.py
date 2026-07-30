"""CalendarEvent repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.calendar_event import CalendarEvent
from app.infra.repositories.base import SoftDeleteRepository


class CalendarEventRepository(SoftDeleteRepository[CalendarEvent]):
    """Persistence operations for calendar events."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CalendarEvent)

    async def list_in_range(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[CalendarEvent]:
        """Return events for a user starting within ``[start, end)``."""
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.start_at >= start,
                CalendarEvent.start_at < end,
                CalendarEvent.deleted_at.is_(None),
            )
            .order_by(CalendarEvent.start_at)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, user_id: uuid.UUID) -> Sequence[CalendarEvent]:
        """Return every non-cancelled, non-deleted event for a user.

        Used by ``CalendarSyncService.sync_user``, which decides per-event
        whether a push is needed by comparing a content hash (see
        ``CalendarEvent.synced_hash``) rather than filtering in SQL --
        calendar events per user are few enough that filtering in
        application code is simpler and avoids timestamp-precision pitfalls
        entirely.
        """
        stmt = select(CalendarEvent).where(
            CalendarEvent.user_id == user_id,
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.status != "cancelled",
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
