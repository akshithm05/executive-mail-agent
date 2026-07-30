"""First-party session repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.session import Session
from app.infra.repositories.base import SQLAlchemyRepository


class SessionRepository(SQLAlchemyRepository[Session]):
    """Persistence operations for first-party login sessions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Session)

    async def get_active_by_token_hash(self, token_hash: str) -> Session | None:
        """Return the non-revoked, non-expired session for a token hash."""
        now = datetime.now(UTC)
        stmt = select(Session).where(
            Session.token_hash == token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, session_row: Session) -> None:
        """Mark a session as revoked, effective immediately."""
        session_row.revoked_at = datetime.now(UTC)
        await self._session.flush()
