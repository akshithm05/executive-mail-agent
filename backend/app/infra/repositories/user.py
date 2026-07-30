"""User repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.user import User
from app.infra.repositories.base import SoftDeleteRepository


class UserRepository(SoftDeleteRepository[User]):
    """Persistence operations for users."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_google_subject(self, google_subject: str) -> User | None:
        """Return the active user with the given Google subject id, or ``None``."""
        stmt = select(User).where(
            User.google_subject == google_subject, User.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Return the active user with the given email, or ``None``."""
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
