"""AuditLog service.

Deliberately does **not** subclass :class:`~app.services.crud.CRUDService`:
that base class exposes ``update`` and ``delete``, and an audit trail the
application itself can edit or hide is not an audit trail. This service only
exposes recording and reading -- there is no code path anywhere that mutates
or removes an existing entry.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.infra.models.audit_log import AuditLog
from app.infra.repositories.audit_log import AuditLogRepository


class AuditLogService:
    """Append-only recording and lookup of audit log entries."""

    def __init__(self, repository: AuditLogRepository) -> None:
        self._repo = repository

    async def record(self, entry: AuditLog) -> AuditLog:
        """Persist a new audit log entry. Entries are never updated or deleted."""
        return await self._repo.add(entry)

    async def get(self, entry_id: uuid.UUID) -> AuditLog | None:
        """Return a single audit log entry by id."""
        return await self._repo.get(entry_id)

    async def list_by_entity(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> Sequence[AuditLog]:
        """Return the audit trail for a specific entity, oldest first."""
        return await self._repo.list_by_entity(entity_type, entity_id)

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[AuditLog]:
        """Return a page of audit log entries."""
        return await self._repo.list(limit=limit, offset=offset)
