"""NotificationDelivery repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import as_naive_utc
from app.infra.models.notification_delivery import NotificationDelivery
from app.infra.repositories.base import SQLAlchemyRepository


class NotificationDeliveryRepository(SQLAlchemyRepository[NotificationDelivery]):
    """Persistence operations for the per-channel delivery audit log."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NotificationDelivery)

    async def list_by_notification(
        self, notification_id: uuid.UUID
    ) -> Sequence[NotificationDelivery]:
        """Return every delivery attempt for one notification, oldest first."""
        stmt = (
            select(NotificationDelivery)
            .where(NotificationDelivery.notification_id == notification_id)
            .order_by(NotificationDelivery.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Hard-delete delivery-log rows created before ``cutoff`` (cleanup sweep).

        ``cutoff`` is normalized to naive UTC (see ``app/core/time.py``) --
        ``created_at`` is a naive column.
        """
        stmt = delete(NotificationDelivery).where(
            NotificationDelivery.created_at < as_naive_utc(cutoff)
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
