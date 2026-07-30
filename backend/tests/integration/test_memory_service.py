"""Integration tests for the long-term memory service and retrieval.

Runs against a real (SQLite-backed) database, exactly like the rest of this
test suite -- no mocking the repository or service layer. The one test that
needs an LLM call (``maybe_summarize``) talks to the same real fake
Anthropic ASGI server used by ``test_email_agent.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from anthropic import AsyncAnthropic
from app.agents.claude_client import StructuredLLMClient
from app.agents.embeddings import HashingEmbeddingProvider
from app.agents.memory_retrieval import MemoryRetrievalService
from app.config.settings import AISettings
from app.infra.db.session import Database
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.memory import MemoryRepository
from app.infra.repositories.prompt_log import PromptLogRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.memory import MemoryService
from httpx import ASGITransport

from tests.fake_anthropic.app import create_fake_anthropic_app


async def _seed_user(database: Database) -> tuple[uuid.UUID, uuid.UUID]:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        user = await UserRepository(session).add(
            User(
                tenant_id=tenant.id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            )
        )
    return tenant.id, user.id


@pytest.mark.asyncio
async def test_upsert_creates_then_reinforces_by_key(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    embedding_provider = HashingEmbeddingProvider(dimensions=64)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        first = await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="important_sender",
            content="Client who always needs fast turnaround.",
            memory_key="client@example.com",
            confidence=0.6,
            embedding_provider=embedding_provider,
        )
        second = await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="important_sender",
            content="Confirmed VIP client, escalate their emails.",
            memory_key="client@example.com",
            confidence=0.8,
            embedding_provider=embedding_provider,
        )

    assert second.id == first.id
    assert second.reinforcement_count == 2
    # Blended, not overwritten: (0.6 + 0.8) / 2.
    assert second.confidence == pytest.approx(0.7)
    assert second.content == "Confirmed VIP client, escalate their emails."
    assert second.embedding_model == embedding_provider.model_name

    async with database.session() as session:
        rows = await MemoryRepository(session).list_by_type(user_id, "important_sender")
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_upsert_without_key_never_reinforces(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="Mentioned traveling next week.",
        )
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="Mentioned a new role change.",
        )

    async with database.session() as session:
        rows = await MemoryRepository(session).list_by_type(user_id, "fact")
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_record_retrieval_bumps_access_stats(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        memory = await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="Some durable fact.",
        )
        assert memory.access_count == 0
        assert memory.last_accessed_at is None

        await service.record_retrieval([memory])

    async with database.session() as session:
        refreshed = await MemoryRepository(session).get(memory.id)
        assert refreshed is not None
        assert refreshed.access_count == 1
        assert refreshed.last_accessed_at is not None


@pytest.mark.asyncio
async def test_decay_sweep_lowers_importance_of_stale_memory(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session), half_life_days=30.0)
        memory = await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="context",
            content="Something situational.",
            confidence=0.8,
        )
        fresh_score = memory.importance_score

        # Simulate the memory going stale: push its last-touched time back
        # by six half-lives, well past the freshness window.
        stale_anchor = datetime.now(UTC) - timedelta(days=180)
        await service.update(memory.id, updated_at=stale_anchor)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session), half_life_days=30.0)
        rescored = await service.run_decay_sweep(user_id)
        assert rescored == 1

    async with database.session() as session:
        refreshed = await MemoryRepository(session).get(memory.id)
        assert refreshed is not None
        assert refreshed.importance_score < fresh_score


@pytest.mark.asyncio
async def test_pinned_memory_is_immune_to_decay_sweep(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        memory = await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="communication_preference",
            content="Always CC my assistant.",
            is_pinned=True,
        )
        assert memory.importance_score == 1.0
        stale_anchor = datetime.now(UTC) - timedelta(days=3650)
        await service.update(memory.id, updated_at=stale_anchor)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        await service.run_decay_sweep(user_id)

    async with database.session() as session:
        refreshed = await MemoryRepository(session).get(memory.id)
        assert refreshed is not None
        assert refreshed.importance_score == 1.0


@pytest.mark.asyncio
async def test_retrieval_returns_structured_and_semantic_matches(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    embedding_provider = HashingEmbeddingProvider(dimensions=128)

    async with database.session() as session:
        repo = MemoryRepository(session)
        service = MemoryService(repo)
        # Structured: keyed to the sender's address, always surfaced for
        # that sender regardless of topical similarity.
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="important_sender",
            content="VIP client, escalate their emails.",
            memory_key="vip@example.com",
            confidence=0.9,
            embedding_provider=embedding_provider,
        )
        # Semantic: topically similar to the query but not sender-keyed.
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="This sender's contracts always require a signature page.",
            confidence=0.7,
            embedding_provider=embedding_provider,
        )
        # Irrelevant noise: should not make the top of the ranking.
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="Unrelated note about the office holiday party.",
            confidence=0.3,
            embedding_provider=embedding_provider,
        )

        retrieval = MemoryRetrievalService(repo, service, embedding_provider)
        recalled = await retrieval.retrieve(
            user_id=user_id,
            from_address="vip@example.com",
            query_text="Please sign the attached contract and return it.",
            top_k=2,
        )

    recalled_types = {m.memory_type for m in recalled}
    assert "important_sender" in recalled_types
    assert any("contract" in m.content.lower() for m in recalled)

    # Retrieval itself reinforces -- access stats should have been bumped.
    async with database.session() as session:
        refreshed = await MemoryRepository(session).list_by_type(
            user_id, "important_sender"
        )
        assert refreshed[0].access_count == 1


@pytest.mark.asyncio
async def test_retrieval_with_no_memories_returns_empty(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)
    embedding_provider = HashingEmbeddingProvider(dimensions=64)

    async with database.session() as session:
        repo = MemoryRepository(session)
        service = MemoryService(repo)
        retrieval = MemoryRetrievalService(repo, service, embedding_provider)
        recalled = await retrieval.retrieve(
            user_id=user_id,
            from_address="nobody@example.com",
            query_text="anything at all",
        )

    assert recalled == []
    assert MemoryRetrievalService.format_for_prompt(recalled) == ""


@pytest.mark.asyncio
async def test_maybe_summarize_consolidates_low_signal_memories(
    database: Database,
) -> None:
    tenant_id, user_id = await _seed_user(database)
    fake_app = create_fake_anthropic_app()

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        for i in range(20):
            await service.upsert(
                tenant_id=tenant_id,
                user_id=user_id,
                memory_type="fact",
                content=f"Observed fact number {i} about this user.",
                confidence=0.5,
            )

    async with (
        httpx.AsyncClient(transport=ASGITransport(app=fake_app)) as http_client,
        database.session() as session,
    ):
        raw_client = AsyncAnthropic(
            api_key="test-key", max_retries=0, http_client=http_client
        )
        claude_client = StructuredLLMClient(
            raw_client,
            AISettings(anthropic_api_key="test-key"),
            PromptLogRepository(session),
        )
        service = MemoryService(MemoryRepository(session), summarization_threshold=20)
        summary = await service.maybe_summarize(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            claude_client=claude_client,
        )
        await raw_client.close()

    assert summary is not None
    assert summary.is_pinned is True
    assert summary.memory_key == "summary:fact"

    async with database.session() as session:
        remaining = await MemoryRepository(session).list_by_type(user_id, "fact")
        assert len(remaining) == 1
        assert remaining[0].id == summary.id


@pytest.mark.asyncio
async def test_maybe_summarize_is_noop_below_threshold(database: Database) -> None:
    tenant_id, user_id = await _seed_user(database)

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session), summarization_threshold=20)
        await service.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            content="Just one fact.",
        )
        result = await service.maybe_summarize(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type="fact",
            claude_client=None,
        )

    assert result is None
