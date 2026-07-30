"""Notification repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.notification import Notification
from app.infra.repositories.base import SoftDeleteRepository


class NotificationRepository(SoftDeleteRepository[Notification]):
    """Persistence operations for in-app notifications."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Notification)

    async def list_unread(self, user_id: uuid.UUID) -> Sequence[Notification]:
        """Return a user's unread notifications, most recent first."""
        stmt = (
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.deleted_at.is_(None),
            )
            .order_by(Notification.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def mark_read(self, notification_id: uuid.UUID) -> Notification | None:
        """Mark a notification as read. Returns ``None`` if it does not exist."""
        notification = await self.get(notification_id)
        if notification is None:
            return None
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        await self._session.flush()
        return notification
