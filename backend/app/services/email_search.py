"""AI-powered hybrid email search: SQL filters + semantic + keyword ranking.

:class:`EmailSearchService` is the second half of the search pipeline (see
``app/services/search_query_parser.py`` for the first half, turning free
text into a :class:`~app.agents.schemas.SearchQueryParseResult`). It:

1. Applies every structured filter at the SQL level (category, is_read,
   has_deadline, a relative date window, and a literal keyword) via
   ``EmailRepository.search_candidates`` -- a bounded, ranked candidate
   pool, mirroring ``MemoryRepository.list_embedding_candidates``'s
   pattern rather than loading a whole mailbox into memory.
2. Scores each candidate in Python: a blend of semantic similarity (cosine
   distance between the query's and the email's embeddings -- see
   ``app/agents/embeddings.py``), a keyword-match bonus, and the email's
   own triage ``priority_score``.
3. Sorts by that blended score (received-time as a stable tiebreaker) and
   slices the requested page.

An email with no embedding yet (not yet reached by the scheduled
``backfill_email_embeddings`` job) still surfaces via SQL filters/keyword
match -- it simply scores 0 on the semantic term rather than being excluded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from app.agents.embeddings import EmbeddingProvider, cosine_similarity
from app.agents.schemas import SearchQueryParseResult
from app.config.settings import SearchSettings
from app.core.time import utcnow
from app.infra.models.email import Email
from app.infra.repositories.email import EmailRepository


@dataclass
class EmailSearchHit:
    """One ranked search result."""

    email: Email
    score: float


@dataclass
class EmailSearchResult:
    """A page of ranked search results, plus the total candidate-pool size."""

    hits: list[EmailSearchHit]
    total: int


class EmailSearchService:
    """Ranks a SQL-filtered candidate pool by semantic + keyword + priority signals."""

    def __init__(
        self,
        email_repo: EmailRepository,
        embedding_provider: EmbeddingProvider,
        settings: SearchSettings,
    ) -> None:
        self._repo = email_repo
        self._embeddings = embedding_provider
        self._settings = settings

    async def search(
        self,
        user_id: uuid.UUID,
        *,
        parsed: SearchQueryParseResult,
        limit: int,
        offset: int,
    ) -> EmailSearchResult:
        """Return one ranked, paginated page of search results.

        ``total`` reflects the size of the (SQL-filtered) candidate pool,
        which is itself capped at ``SearchSettings.candidate_limit`` --
        pagination beyond that cap is not supported, matching the same
        bounded-pool tradeoff the memory-retrieval system already makes.
        """
        since = (
            utcnow() - timedelta(days=parsed.days_back) if parsed.days_back else None
        )
        candidates = await self._repo.search_candidates(
            user_id,
            category=parsed.category,
            is_read=parsed.is_read,
            has_deadline=parsed.has_deadline,
            since=since,
            keyword=parsed.keyword,
            limit=self._settings.candidate_limit,
        )

        query_embedding = self._embeddings.embed(parsed.semantic_query)
        hits = [
            self._score(email, query_embedding, parsed.keyword) for email in candidates
        ]
        hits.sort(key=lambda hit: (hit.score, hit.email.received_at), reverse=True)

        total = len(hits)
        page = hits[offset : offset + limit]
        return EmailSearchResult(hits=page, total=total)

    def _score(
        self, email: Email, query_embedding: list[float], keyword: str | None
    ) -> EmailSearchHit:
        semantic = 0.0
        if email.embedding:
            semantic = max(cosine_similarity(query_embedding, email.embedding), 0.0)

        keyword_hit = 0.0
        if keyword:
            haystack = f"{email.subject}\n{email.body_text or ''}\n{email.from_address}"
            if keyword.lower() in haystack.lower():
                keyword_hit = 1.0

        priority = email.priority_score or 0.0
        score = (
            self._settings.semantic_weight * semantic
            + self._settings.keyword_weight * keyword_hit
            + self._settings.priority_weight * priority
        )
        return EmailSearchHit(email=email, score=score)
