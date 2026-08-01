"""PushDevice repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.push_device import PushDevice
from app.infra.repositories.base import SQLAlchemyRepository


class PushDeviceRepository(SQLAlchemyRepository[PushDevice]):
    """Persistence operations for registered push (web/mobile) devices."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PushDevice)

    async def list_active_by_user_and_platforms(
        self, user_id: uuid.UUID, platforms: Sequence[str]
    ) -> Sequence[PushDevice]:
        """Return a user's active devices restricted to the given platforms."""
        stmt = select(PushDevice).where(
            PushDevice.user_id == user_id,
            PushDevice.is_active.is_(True),
            PushDevice.platform.in_(platforms),
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[PushDevice]:
        """Return every device (active or not) for a user."""
        stmt = select(PushDevice).where(PushDevice.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()
