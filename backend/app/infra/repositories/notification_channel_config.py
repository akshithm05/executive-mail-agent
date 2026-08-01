"""NotificationChannelConfig repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.notification_channel_config import NotificationChannelConfig
from app.infra.repositories.base import SQLAlchemyRepository


class NotificationChannelConfigRepository(
    SQLAlchemyRepository[NotificationChannelConfig]
):
    """Persistence operations for per-user singleton channel configs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NotificationChannelConfig)

    async def get_by_user_and_channel(
        self, user_id: uuid.UUID, channel_type: str
    ) -> NotificationChannelConfig | None:
        """Return a user's config for one channel type, or ``None`` if unset."""
        stmt = select(NotificationChannelConfig).where(
            NotificationChannelConfig.user_id == user_id,
            NotificationChannelConfig.channel_type == channel_type,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_enabled_by_user(
        self, user_id: uuid.UUID
    ) -> Sequence[NotificationChannelConfig]:
        """Return every enabled channel config for a user."""
        stmt = select(NotificationChannelConfig).where(
            NotificationChannelConfig.user_id == user_id,
            NotificationChannelConfig.is_enabled.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_user(
        self, user_id: uuid.UUID
    ) -> Sequence[NotificationChannelConfig]:
        """Return every channel config for a user, enabled or not."""
        stmt = select(NotificationChannelConfig).where(
            NotificationChannelConfig.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
