"""NotificationRule repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.notification_rule import NotificationRule
from app.infra.repositories.base import SQLAlchemyRepository


class NotificationRuleRepository(SQLAlchemyRepository[NotificationRule]):
    """Persistence operations for per-user custom notification rules."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NotificationRule)

    async def list_enabled_by_user(
        self, user_id: uuid.UUID
    ) -> Sequence[NotificationRule]:
        """Return a user's enabled rules."""
        stmt = select(NotificationRule).where(
            NotificationRule.user_id == user_id, NotificationRule.is_enabled.is_(True)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[NotificationRule]:
        """Return every rule (enabled or not) for a user."""
        stmt = select(NotificationRule).where(NotificationRule.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()
