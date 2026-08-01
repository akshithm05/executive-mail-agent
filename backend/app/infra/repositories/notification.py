"""Notification repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_naive_utc, utcnow
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

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Notification]:
        """Return a user's notifications, most recent first."""
        stmt = select(Notification).where(
            Notification.user_id == user_id, Notification.deleted_at.is_(None)
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """Return the number of a user's unread notifications."""
        stmt = select(func.count()).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
            Notification.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def mark_read(self, notification_id: uuid.UUID) -> Notification | None:
        """Mark a notification as read. Returns ``None`` if it does not exist.

        Refreshes after flush -- see the equivalent note on
        ``SQLAlchemyRepository.update_fields`` (``app/infra/repositories/
        base.py``): without it, the server-computed ``updated_at`` column is
        left expired, and a later synchronous attribute read (e.g. Pydantic's
        ``model_validate`` in a route handler) crashes with ``MissingGreenlet``.
        """
        notification = await self.get(notification_id)
        if notification is None:
            return None
        notification.is_read = True
        notification.read_at = utcnow()
        await self._session.flush()
        await self._session.refresh(notification)
        return notification

    async def delete_read_older_than(self, cutoff: datetime) -> int:
        """Hard-delete read notifications created before ``cutoff``.

        Used by the scheduled cleanup sweep. Unread notifications are never
        purged this way, regardless of age -- only ones the user has
        already seen. ``cutoff`` is normalized to naive UTC before the
        comparison -- ``created_at`` is a naive column (see
        ``app/core/time.py``), and Postgres's asyncpg driver rejects an
        aware value bound against it.
        """
        stmt = delete(Notification).where(
            Notification.is_read.is_(True),
            Notification.created_at < as_naive_utc(cutoff),
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
