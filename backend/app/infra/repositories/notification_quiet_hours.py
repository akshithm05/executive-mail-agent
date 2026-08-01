"""NotificationQuietHours repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.notification_quiet_hours import NotificationQuietHours
from app.infra.repositories.base import SQLAlchemyRepository


class NotificationQuietHoursRepository(SQLAlchemyRepository[NotificationQuietHours]):
    """Persistence operations for a user's (singleton) quiet-hours config."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NotificationQuietHours)

    async def get_by_user(self, user_id: uuid.UUID) -> NotificationQuietHours | None:
        """Return a user's quiet-hours config, or ``None`` if never configured."""
        stmt = select(NotificationQuietHours).where(
            NotificationQuietHours.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
