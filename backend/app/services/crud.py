"""Generic CRUD service.

Wraps a :class:`~app.infra.repositories.base.SoftDeleteRepository` with a
thin, uniform create/read/update/soft-delete surface so route handlers (and
future LangGraph tools) depend on a service abstraction rather than the
repository directly. Concrete per-entity services subclass this to add
domain-specific behavior; entities that need nothing beyond CRUD can use
this directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from app.infra.db.base import Base
from app.infra.repositories.base import SoftDeleteRepository

ModelT = TypeVar("ModelT", bound=Base)


class CRUDService(Generic[ModelT]):
    """Generic create/read/update/soft-delete service over one ORM model.

    Args:
        repository: The soft-delete-aware repository for this model, bound
            to the request-scoped session.
    """

    def __init__(self, repository: SoftDeleteRepository[ModelT]) -> None:
        self._repo = repository

    async def create(self, entity: ModelT) -> ModelT:
        """Persist a new, transient entity."""
        return await self._repo.add(entity)

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Return an active (non-deleted) entity by id, or ``None``."""
        return await self._repo.get(entity_id)

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ModelT]:
        """Return a page of active entities."""
        return await self._repo.list(limit=limit, offset=offset)

    async def count(self) -> int:
        """Return the number of active entities."""
        return await self._repo.count()

    async def update(self, entity_id: uuid.UUID, **fields: Any) -> ModelT | None:
        """Update one or more column values on an entity, or ``None`` if absent."""
        return await self._repo.update_fields(entity_id, **fields)

    async def delete(self, entity_id: uuid.UUID) -> bool:
        """Soft-delete an entity. Returns ``False`` if it did not exist."""
        return await self._repo.soft_delete(entity_id)
