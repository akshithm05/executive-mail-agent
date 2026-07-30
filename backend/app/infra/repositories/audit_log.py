"""AuditLog repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.audit_log import AuditLog
from app.infra.repositories.base import SoftDeleteRepository


class AuditLogRepository(SoftDeleteRepository[AuditLog]):
    """Persistence operations for audit log entries.

    Inherits from :class:`SoftDeleteRepository` purely for read-filtering
    consistency with the rest of the codebase; ``soft_delete`` exists on the
    class but is never called by :class:`~app.services.audit_log.AuditLogService`
    -- see the immutability note on :class:`~app.infra.models.audit_log.AuditLog`.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)

    async def list_by_entity(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> Sequence[AuditLog]:
        """Return the audit trail for a specific entity, oldest first."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
