"""Generic async repository.

The repository pattern isolates persistence concerns behind a narrow, typed
interface so that services and (later) LangGraph tools depend on an abstraction
rather than on SQLAlchemy directly. :class:`SQLAlchemyRepository` provides the
common CRUD operations; concrete repositories subclass it to add
model-specific queries.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class SQLAlchemyRepository(Generic[ModelT]):
    """Base repository providing CRUD over a single ORM model.

    Args:
        session: The active :class:`AsyncSession`. The session's transaction is
            owned by the caller (typically the request-scoped dependency), so
            repository methods flush but do not commit.
        model: The ORM model class this repository manages.
    """

    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self._session = session
        self._model = model

    async def add(self, entity: ModelT) -> ModelT:
        """Persist a new entity and flush so its defaults are populated.

        Args:
            entity: A transient ORM instance.

        Returns:
            The same instance, now flushed to the session.
        """
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Return the entity with the given id, or ``None`` if absent."""
        return await self._session.get(self._model, entity_id)

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ModelT]:
        """Return a page of entities ordered by primary key.

        Args:
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.
        """
        stmt = select(self._model).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """Return the total number of rows for this model."""
        stmt = select(func.count()).select_from(self._model)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def delete(self, entity_id: uuid.UUID) -> bool:
        """Delete the entity with the given id.

        Returns:
            True if a row was deleted, False if no matching row existed.
        """
        stmt = delete(self._model).where(self._model.id == entity_id)  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return bool(result.rowcount)

    async def update_fields(self, entity_id: uuid.UUID, **fields: Any) -> ModelT | None:
        """Set arbitrary column attributes on an entity and flush.

        Used by the generic CRUD service layer (``app/services/crud.py``) so
        it does not need to know which columns exist on each model.

        Refreshes the entity after flushing: an ``onupdate=func.now()``
        column (``updated_at``, see ``TimestampMixin``) is server-computed,
        so after a flush its in-memory value is expired pending a reload.
        Reading an expired attribute triggers a lazy load, which -- unlike a
        normal lazy load awaited by application code -- happens synchronously
        wherever the attribute is next touched (e.g. inside Pydantic's
        ``model_validate(entity, from_attributes=True)`` in a route handler),
        and SQLAlchemy's async engine cannot service that without an
        explicit ``await``, raising ``MissingGreenlet``. Refreshing here
        (still inside an awaited call) guarantees every attribute is already
        loaded before this method returns.

        Returns:
            The updated entity, or ``None`` if no row with this id exists.
        """
        entity = await self.get(entity_id)
        if entity is None:
            return None
        for key, value in fields.items():
            setattr(entity, key, value)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity


class SoftDeleteRepository(SQLAlchemyRepository[ModelT]):
    """Repository base for models using :class:`~app.infra.db.mixins.SoftDeleteMixin`.

    Overrides reads to exclude soft-deleted rows by default and adds
    :meth:`soft_delete`, which sets ``deleted_at`` instead of removing the
    row. The inherited :meth:`~SQLAlchemyRepository.delete` is still
    available for callers that genuinely need a hard delete (e.g. GDPR
    erasure requests), but everyday application code should call
    :meth:`soft_delete`.
    """

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Return the entity with the given id, unless it is soft-deleted."""
        entity = await super().get(entity_id)
        if entity is not None and entity.deleted_at is not None:  # type: ignore[attr-defined]
            return None
        return entity

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ModelT]:
        """Return a page of non-deleted entities ordered by primary key."""
        stmt = (
            select(self._model)
            .where(self._model.deleted_at.is_(None))  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """Return the number of non-deleted rows for this model."""
        stmt = (
            select(func.count())
            .select_from(self._model)
            .where(self._model.deleted_at.is_(None))  # type: ignore[attr-defined]
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def soft_delete(self, entity_id: uuid.UUID) -> bool:
        """Mark the entity as deleted without removing the row.

        Returns:
            True if an active (not already deleted) row was found and
            marked; False if no such row exists.
        """
        entity = await SQLAlchemyRepository.get(self, entity_id)
        if entity is None or entity.deleted_at is not None:  # type: ignore[attr-defined]
            return False
        entity.deleted_at = datetime.now(UTC)  # type: ignore[attr-defined]
        await self._session.flush()
        return True
