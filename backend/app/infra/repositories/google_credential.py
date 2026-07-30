"""Google credential repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.google_credential import GoogleCredential
from app.infra.repositories.base import SQLAlchemyRepository


class GoogleCredentialRepository(SQLAlchemyRepository[GoogleCredential]):
    """Persistence operations for encrypted Google OAuth credentials."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GoogleCredential)

    async def get_by_user_id(self, user_id: uuid.UUID) -> GoogleCredential | None:
        """Return the credential for the given user, or ``None``."""
        stmt = select(GoogleCredential).where(GoogleCredential.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
