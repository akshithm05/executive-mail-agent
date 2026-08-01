"""Preference repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.preference import Preference
from app.infra.repositories.base import SoftDeleteRepository


class PreferenceRepository(SoftDeleteRepository[Preference]):
    """Persistence operations for user preferences."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Preference)

    async def get_by_key(self, user_id: uuid.UUID, key: str) -> Preference | None:
        """Return a user's preference by key, or ``None`` if unset."""
        stmt = select(Preference).where(
            Preference.user_id == user_id,
            Preference.key == key,
            Preference.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[Preference]:
        """Return every active preference for a user."""
        stmt = select(Preference).where(
            Preference.user_id == user_id, Preference.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
