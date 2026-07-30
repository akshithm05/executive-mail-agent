"""Tenant repository.

Concrete repository for the :class:`~app.infra.models.tenant.Tenant` model. It
inherits generic CRUD from :class:`SQLAlchemyRepository` and adds the
tenant-specific lookup by slug.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.tenant import Tenant
from app.infra.repositories.base import SQLAlchemyRepository


class TenantRepository(SQLAlchemyRepository[Tenant]):
    """Persistence operations for tenants."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Tenant)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Return the tenant with the given unique slug, or ``None``."""
        stmt = select(Tenant).where(Tenant.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
