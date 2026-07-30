"""Long-term memory retrieval for the email-triage graph.

Combines two retrieval strategies into one ranked, deduplicated list:

* **Structured recall** -- every pinned memory, plus every memory of a type
  that should always be considered about a known entity regardless of
  topical similarity (``important_sender``, ``communication_preference``,
  ``priority_rule``, ``archive_behavior``, ``reply_style``), filtered to
  ones whose ``memory_key`` matches the current email's sender, or with no
  key at all (categories that are inherently per-user, not per-sender).
* **Semantic recall** -- embed the current email's subject+body, cosine-
  similarity-rank a bounded candidate pool of embedded memories (see
  ``MemoryRepository.list_embedding_candidates``), and take the top
  matches, weighted by both similarity *and* decay-adjusted importance so a
  highly important but loosely related memory can still outrank a highly
  similar but stale one.

The merged result is what gets formatted into the "known context about this
user" block injected into the categorize/priority/reply_decision/
reply_draft/calendar_suggestion prompts (see ``app/agents/graph.py``'s
``recall_memory`` node and ``_email_context``) -- this is the read side of
the memory loop Phase 5 only wrote to.
"""

from __future__ import annotations

import uuid

from app.agents.embeddings import EmbeddingProvider, cosine_similarity
from app.infra.models.memory import Memory
from app.infra.repositories.memory import MemoryRepository
from app.services.memory import MemoryService

_ALWAYS_RELEVANT_TYPES = (
    "important_sender",
    "communication_preference",
    "priority_rule",
    "archive_behavior",
    "reply_style",
)

_SIMILARITY_WEIGHT = 0.6
_IMPORTANCE_WEIGHT = 0.4


class MemoryRetrievalService:
    """Fetches and ranks the memories relevant to one incoming email."""

    def __init__(
        self,
        repository: MemoryRepository,
        service: MemoryService,
        embedding_provider: EmbeddingProvider,
        *,
        default_top_k: int = 6,
    ) -> None:
        self._repo = repository
        self._service = service
        self._embeddings = embedding_provider
        self._default_top_k = default_top_k

    async def retrieve(
        self,
        *,
        user_id: uuid.UUID,
        from_address: str,
        query_text: str,
        top_k: int | None = None,
    ) -> list[Memory]:
        """Return the most relevant, decay-aware memories for this email.

        Also records the retrieval (see
        ``MemoryService.record_retrieval``) -- being surfaced here is itself
        a reinforcement signal that slows a memory's decay.
        """
        top_k = top_k if top_k is not None else self._default_top_k
        structured = await self._repo.list_pinned_and_structured(
            user_id, memory_types=_ALWAYS_RELEVANT_TYPES
        )
        from_address_lower = from_address.strip().lower()
        relevant_structured = [
            m
            for m in structured
            if m.is_pinned
            or m.memory_key is None
            or m.memory_key.strip().lower() == from_address_lower
        ]

        semantic = await self._semantic_search(
            user_id, query_text=query_text, top_k=top_k
        )

        merged: dict[uuid.UUID, Memory] = {}
        for memory in (*relevant_structured, *semantic):
            merged[memory.id] = memory

        ranked = sorted(merged.values(), key=lambda m: m.importance_score, reverse=True)
        selected = ranked[: max(top_k, len(relevant_structured))]
        if selected:
            await self._service.record_retrieval(selected)
        return selected

    async def _semantic_search(
        self, user_id: uuid.UUID, *, query_text: str, top_k: int
    ) -> list[Memory]:
        if not query_text:
            return []
        query_embedding = self._embeddings.embed(query_text)
        candidates = await self._repo.list_embedding_candidates(user_id)

        scored: list[tuple[float, Memory]] = []
        for candidate in candidates:
            if candidate.embedding is None:
                continue
            similarity = cosine_similarity(query_embedding, candidate.embedding)
            score = (
                _SIMILARITY_WEIGHT * max(similarity, 0.0)
                + _IMPORTANCE_WEIGHT * candidate.importance_score
            )
            scored.append((score, candidate))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [memory for _, memory in scored[:top_k]]

    @staticmethod
    def format_for_prompt(memories: list[Memory]) -> str:
        """Render recalled memories as a prompt-ready context block."""
        if not memories:
            return ""
        lines = [
            f"- [{m.memory_type}] {m.content} (confidence {m.confidence:.2f})"
            for m in memories
        ]
        return "Known context about this user, from past interactions:\n" + "\n".join(
            lines
        )
