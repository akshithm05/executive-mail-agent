"""Long-term memory service.

Beyond plain CRUD (inherited from :class:`~app.services.crud.CRUDService`),
this is where the long-term memory subsystem's behavior lives:

* :meth:`upsert` -- create-or-reinforce by ``memory_key``, so the same fact
  observed again (e.g. the same sender emailing a second time) strengthens
  one row instead of creating a duplicate.
* :meth:`record_retrieval` -- retrieval itself is a reinforcement signal:
  a memory that keeps getting surfaced to the LLM decays slower than one
  nobody has needed.
* :meth:`run_decay_sweep` -- batch recompute of every non-pinned memory's
  ``importance_score`` against the current time. Not wired to a scheduler
  (this codebase has none yet), but callable from one later, or from an
  admin endpoint/CLI, without any other change.
* :meth:`maybe_summarize` -- once a user accumulates many low-signal
  memories of the same type, consolidate them into one higher-confidence,
  pinned summary memory via an LLM call, soft-deleting the originals. Keeps
  the memory store from growing into noise that dilutes retrieval.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from app.agents import prompts
from app.agents.embeddings import EmbeddingProvider
from app.agents.memory_scoring import DEFAULT_HALF_LIFE_DAYS, compute_importance_score
from app.config.logging import get_logger
from app.core.time import utcnow
from app.infra.models.memory import Memory
from app.infra.repositories.memory import MemoryRepository
from app.services.crud import CRUDService

logger = get_logger(__name__)

# Below this many non-pinned memories of the same type, summarization is not
# worth an extra LLM call -- the store isn't noisy yet.
_DEFAULT_SUMMARIZATION_THRESHOLD = 20


class MemoryService(CRUDService[Memory]):
    """CRUD operations for long-term AI memory entries, plus memory behavior."""

    def __init__(
        self,
        repository: MemoryRepository,
        *,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        summarization_threshold: int = _DEFAULT_SUMMARIZATION_THRESHOLD,
    ) -> None:
        super().__init__(repository)
        self._repo: MemoryRepository = repository
        self._half_life_days = half_life_days
        self._summarization_threshold = summarization_threshold

    async def list_by_type(
        self, user_id: uuid.UUID, memory_type: str
    ) -> Sequence[Memory]:
        """Return a user's memories of a given type."""
        return await self._repo.list_by_type(user_id, memory_type)

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        memory_type: str,
        content: str,
        memory_key: str | None = None,
        confidence: float = 0.5,
        source_email_id: uuid.UUID | None = None,
        extra_metadata: dict[str, Any] | None = None,
        is_pinned: bool = False,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> Memory:
        """Create a new memory, or reinforce the existing one for this key.

        Reinforcement blends confidence (a weighted average, not a plain
        overwrite -- a single weak repeat shouldn't spike confidence) and
        bumps ``reinforcement_count``, which feeds
        :func:`~app.agents.memory_scoring.reinforcement_boost`.
        """
        embedding = embedding_provider.embed(content) if embedding_provider else None
        embedding_model = embedding_provider.model_name if embedding_provider else None
        now = utcnow()

        existing = (
            await self._repo.get_by_key(user_id, memory_type, memory_key)
            if memory_key
            else None
        )
        if existing is not None:
            merged_metadata = {**existing.extra_metadata, **(extra_metadata or {})}
            existing.content = content
            existing.confidence = (existing.confidence + confidence) / 2
            existing.reinforcement_count += 1
            existing.is_pinned = existing.is_pinned or is_pinned
            existing.extra_metadata = merged_metadata
            if source_email_id is not None:
                existing.source_email_id = source_email_id
            if embedding is not None:
                existing.embedding = embedding
                existing.embedding_model = embedding_model
            existing.importance_score = compute_importance_score(
                existing, now=now, half_life_days=self._half_life_days
            )
            updated = await self.update(
                existing.id,
                content=existing.content,
                confidence=existing.confidence,
                reinforcement_count=existing.reinforcement_count,
                is_pinned=existing.is_pinned,
                extra_metadata=existing.extra_metadata,
                source_email_id=existing.source_email_id,
                embedding=existing.embedding,
                embedding_model=existing.embedding_model,
                importance_score=existing.importance_score,
            )
            return cast(Memory, updated)

        memory = Memory(
            tenant_id=tenant_id,
            user_id=user_id,
            source_email_id=source_email_id,
            memory_type=memory_type,
            memory_key=memory_key,
            content=content,
            confidence=confidence,
            is_pinned=is_pinned,
            extra_metadata=extra_metadata or {},
            embedding=embedding,
            embedding_model=embedding_model,
        )
        memory.importance_score = compute_importance_score(
            memory, now=now, half_life_days=self._half_life_days
        )
        return await self.create(memory)

    async def record_retrieval(self, memories: Sequence[Memory]) -> None:
        """Bump access stats for memories that were just surfaced to the LLM.

        Being retrieved is itself a reinforcement signal -- a memory that
        keeps getting used should decay slower than one sitting unused,
        which is why this recomputes ``importance_score`` too rather than
        just touching the timestamp.
        """
        now = utcnow()
        for memory in memories:
            memory.access_count += 1
            memory.last_accessed_at = now
            new_score = compute_importance_score(
                memory, now=now, half_life_days=self._half_life_days
            )
            await self.update(
                memory.id,
                access_count=memory.access_count,
                last_accessed_at=now,
                importance_score=new_score,
            )

    async def run_decay_sweep(self, user_id: uuid.UUID | None = None) -> int:
        """Recompute ``importance_score`` for every active memory.

        Not wired to a scheduler (none exists in this codebase yet) --
        callable from a future cron job, background task, or admin CLI.
        Pinned memories are included but score 1.0 regardless, so the sweep
        is idempotent and safe to run at any cadence.

        Returns:
            The number of memories rescored.
        """
        memories = await self._repo.list_all_active(user_id)
        now = utcnow()
        for memory in memories:
            new_score = compute_importance_score(
                memory, now=now, half_life_days=self._half_life_days
            )
            if new_score != memory.importance_score:
                await self.update(memory.id, importance_score=new_score)
        return len(memories)

    async def maybe_summarize(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        memory_type: str,
        claude_client: Any,
        embedding_provider: EmbeddingProvider | None = None,
        threshold: int | None = None,
    ) -> Memory | None:
        """Consolidate many low-signal memories of one type into a summary.

        No-op below ``threshold`` non-pinned memories of this type. On
        summarization: creates one new pinned, high-confidence memory
        capturing the consolidated pattern, then soft-deletes the originals
        so retrieval sees the summary instead of the noise it was built
        from.

        Callers (the graph's ``database_update`` node) are expected to catch
        exceptions from this and degrade gracefully -- a failed
        summarization should never fail the email-triage pipeline it's
        piggybacking on.
        """
        from app.agents.schemas import MemorySummaryResult  # local: avoid cycle

        threshold = (
            threshold if threshold is not None else self._summarization_threshold
        )
        candidates = [
            m
            for m in await self._repo.list_by_type(user_id, memory_type)
            if not m.is_pinned
        ]
        if len(candidates) < threshold:
            return None

        bullets = "\n".join(f"- {m.content}" for m in candidates)
        result: MemorySummaryResult = await claude_client.complete(
            system=prompts.MEMORY_SUMMARIZATION_SYSTEM,
            user_message=bullets,
            response_model=MemorySummaryResult,
            tenant_id=tenant_id,
            user_id=user_id,
            ai_history_id=None,
            node_name="memory_summarization",
        )

        summary = await self.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type=memory_type,
            content=result.summary,
            memory_key=f"summary:{memory_type}",
            confidence=result.confidence,
            is_pinned=True,
            extra_metadata={"summarized_count": len(candidates)},
            embedding_provider=embedding_provider,
        )
        for candidate in candidates:
            await self._repo.soft_delete(candidate.id)

        logger.info(
            "memory_summarized",
            user_id=str(user_id),
            memory_type=memory_type,
            consolidated_count=len(candidates),
        )
        return summary
