"""Integration tests for the LLM-backed half of :class:`SearchQueryParser`.

Drives it against the fake Anthropic server (real HTTP, real JSON) rather
than mocking the client -- see ``tests/fake_anthropic/app.py``.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from anthropic import AsyncAnthropic
from app.agents.claude_client import StructuredLLMClient
from app.config.settings import AISettings, Settings
from app.infra.db.session import Database
from app.infra.repositories.prompt_log import PromptLogRepository
from app.services.search_query_parser import SearchQueryParser
from httpx import ASGITransport

from tests.fake_anthropic.app import FakeAnthropicState, create_fake_anthropic_app


def _settings_with_ai() -> Settings:
    return Settings(
        environment="test",
        log_format="console",
        log_level="WARNING",
        ai=AISettings(anthropic_api_key="test-key"),
    )


@pytest.mark.asyncio
async def test_parse_uses_the_llm_when_ai_is_configured(database: Database) -> None:
    fake_app = create_fake_anthropic_app()
    state: FakeAnthropicState = fake_app.state.fake_anthropic
    settings = _settings_with_ai()

    async with httpx.AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        raw_client = AsyncAnthropic(
            api_key=settings.ai.anthropic_api_key,
            http_client=http_client,
            max_retries=0,
        )
        async with database.session() as session:
            llm_client = StructuredLLMClient(
                raw_client, settings.ai, PromptLogRepository(session)
            )
            parser = SearchQueryParser(llm_client, settings.ai)
            result = await parser.parse(
                "Show recruiter emails", tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
            )

    assert state.call_count == 1
    assert result.semantic_query == "recruiter emails"
    assert result.confidence == 0.85


@pytest.mark.asyncio
async def test_parse_falls_back_to_heuristic_on_llm_failure(database: Database) -> None:
    fake_app = create_fake_anthropic_app()
    state: FakeAnthropicState = fake_app.state.fake_anthropic
    state.fail_fields.add("semantic_query")
    settings = _settings_with_ai()

    async with httpx.AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        raw_client = AsyncAnthropic(
            api_key=settings.ai.anthropic_api_key,
            http_client=http_client,
            max_retries=0,
        )
        async with database.session() as session:
            fast_fail_settings = AISettings(anthropic_api_key="test-key", max_retries=1)
            llm_client = StructuredLLMClient(
                raw_client, fast_fail_settings, PromptLogRepository(session)
            )
            parser = SearchQueryParser(llm_client, settings.ai)
            result = await parser.parse(
                "Unread invoices", tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
            )

    # Fell back to the heuristic parser -- still usable, just lower-fidelity.
    assert result.semantic_query == "Unread invoices"
    assert result.is_read is False
    assert result.confidence == 0.3


@pytest.mark.asyncio
async def test_parse_skips_the_llm_entirely_when_ai_not_configured(
    database: Database,
) -> None:
    unconfigured = AISettings(anthropic_api_key="")

    async with database.session() as session:
        # A client that would error on any real call -- never invoked since
        # `is_configured` is False and the parser must short-circuit first.
        raw_client = AsyncAnthropic(api_key="", max_retries=0)
        llm_client = StructuredLLMClient(
            raw_client, unconfigured, PromptLogRepository(session)
        )
        parser = SearchQueryParser(llm_client, unconfigured)
        result = await parser.parse(
            "Internship offers", tenant_id=uuid.uuid4(), user_id=uuid.uuid4()
        )

    assert result.semantic_query == "Internship offers"
    assert result.confidence == 0.3
