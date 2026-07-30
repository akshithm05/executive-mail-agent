"""Memory repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.memory import Memory
from app.infra.repositories.base import SoftDeleteRepository

# How many candidate rows to pull back for an in-application similarity scan
# (see ``list_embedding_candidates``). Bounded so retrieval stays cheap even
# for a user with thousands of memories -- ranked by the same importance
# score used elsewhere, so the candidates considered are already the most
# durable/relevant ones, not an arbitrary slice.
_DEFAULT_CANDIDATE_LIMIT = 200


class MemoryRepository(SoftDeleteRepository[Memory]):
    """Persistence operations for long-term AI memory entries."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Memory)

    async def list_by_type(
        self, user_id: uuid.UUID, memory_type: str
    ) -> Sequence[Memory]:
        """Return a user's memories of a given type."""
        stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.memory_type == memory_type,
            Memory.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_by_key(
        self, user_id: uuid.UUID, memory_type: str, memory_key: str
    ) -> Memory | None:
        """Look up a reinforceable memory by its stable dedupe key.

        Used by :meth:`~app.services.memory.MemoryService.upsert` to decide
        whether a new observation reinforces an existing row (e.g. the same
        sender emailing again) instead of creating a duplicate.
        """
        stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.memory_type == memory_type,
            Memory.memory_key == memory_key,
            Memory.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pinned_and_structured(
        self, user_id: uuid.UUID, *, memory_types: Sequence[str]
    ) -> Sequence[Memory]:
        """Return every pinned memory plus all memories of the given types.

        This is the *structured* half of retrieval (see
        ``MemoryRetrievalService``): deterministic, not similarity-ranked --
        e.g. "always surface every known important_sender and
        communication_preference," regardless of how similar their content
        is to the current email.
        """
        stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.deleted_at.is_(None),
            (Memory.is_pinned.is_(True)) | (Memory.memory_type.in_(memory_types)),
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_embedding_candidates(
        self, user_id: uuid.UUID, *, limit: int = _DEFAULT_CANDIDATE_LIMIT
    ) -> Sequence[Memory]:
        """Return a bounded, importance-ranked set of embedded memories.

        Semantic similarity search today is an in-application cosine-
        similarity scan (see ``app/agents/embeddings.py::cosine_similarity``)
        over the rows this method returns -- this is the seam to replace
        with a real vector index later: swap this method's body for a
        ``pgvector`` ``ORDER BY embedding <-> :query LIMIT k`` query, or a
        call to an external vector database, and no caller
        (``MemoryRetrievalService``) needs to change.
        """
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.deleted_at.is_(None),
                Memory.embedding.is_not(None),
            )
            .order_by(Memory.importance_score.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_all_active(
        self, user_id: uuid.UUID | None = None
    ) -> Sequence[Memory]:
        """Return every non-deleted memory, optionally scoped to one user.

        Used by :meth:`~app.services.memory.MemoryService.run_decay_sweep`,
        which needs every row to recompute ``importance_score`` against.
        """
        stmt = select(Memory).where(Memory.deleted_at.is_(None))
        if user_id is not None:
            stmt = stmt.where(Memory.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()
