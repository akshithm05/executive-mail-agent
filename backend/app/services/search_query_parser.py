"""Parses a free-text AI-powered-search query into structured filters.

Two-tier, matching this codebase's established graceful-degradation
pattern (see ``run_email_triage``/``run_memory_consolidation`` in
``app/scheduler.py``): Claude does the real extraction (category
inference, literal company/person names, nuanced relative dates) when
``settings.ai.is_configured``; otherwise -- or if the LLM call itself
fails -- :func:`heuristic_parse` (pure regex, no I/O) takes over. Either
way the caller always gets a usable ``SearchQueryParseResult``, so search
never goes fully blind just because AI isn't configured.
"""

from __future__ import annotations

import re
import uuid

from app.agents.claude_client import StructuredLLMClient
from app.agents.prompts import (
    SEARCH_QUERY_PARSE_SYSTEM,
    search_query_parse_user_message,
)
from app.agents.schemas import SearchQueryParseResult
from app.config.logging import get_logger
from app.config.settings import AISettings
from app.core.time import utcnow

logger = get_logger(__name__)

_UNREAD_PATTERN = re.compile(r"\bunread\b", re.IGNORECASE)
_READ_PATTERN = re.compile(r"(?<!un)\bread\b", re.IGNORECASE)

# Relative-date phrase -> approximate days back from today. Deliberately
# coarse (a heuristic fallback, not language understanding) -- checked
# longest/most-specific phrase first so "last month" doesn't get shadowed
# by a hypothetical looser match.
_RELATIVE_DATE_PHRASES: tuple[tuple[str, int], ...] = (
    ("yesterday", 2),
    ("today", 1),
    ("last week", 14),
    ("this week", 7),
    ("last month", 60),
    ("this month", 31),
)


def heuristic_parse(query: str) -> SearchQueryParseResult:
    """Cheap, dependency-free query parsing -- the fallback path.

    Handles the two signals a regex can reliably extract (unread/read,
    common relative-date phrases). Category inference, literal keyword
    extraction, and deadline intent are left to embedding similarity
    against the raw query text, which needs no language understanding to
    be useful -- see ``app/services/email_search.py``.
    """
    lowered = query.lower()
    is_read: bool | None = None
    if _UNREAD_PATTERN.search(lowered):
        is_read = False
    elif _READ_PATTERN.search(lowered):
        is_read = True

    days_back: int | None = None
    for phrase, days in _RELATIVE_DATE_PHRASES:
        if phrase in lowered:
            days_back = days
            break

    return SearchQueryParseResult(
        semantic_query=query,
        category=None,
        is_read=is_read,
        has_deadline=None,
        days_back=days_back,
        keyword=None,
        confidence=0.3,
    )


class SearchQueryParser:
    """Parses a free-text search query into structured filters + a semantic query."""

    def __init__(
        self, llm_client: StructuredLLMClient, ai_settings: AISettings
    ) -> None:
        self._llm_client = llm_client
        self._ai_settings = ai_settings

    async def parse(
        self, query: str, *, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> SearchQueryParseResult:
        """Parse ``query``, using Claude when configured, heuristics otherwise."""
        if not self._ai_settings.is_configured:
            return heuristic_parse(query)
        try:
            return await self._llm_client.complete(
                system=SEARCH_QUERY_PARSE_SYSTEM,
                user_message=search_query_parse_user_message(
                    query, today=utcnow().date().isoformat()
                ),
                response_model=SearchQueryParseResult,
                tenant_id=tenant_id,
                user_id=user_id,
                ai_history_id=None,
                node_name="search_query_parse",
            )
        except Exception:
            logger.warning("search_query_parse_llm_failed", query=query, exc_info=True)
            return heuristic_parse(query)
