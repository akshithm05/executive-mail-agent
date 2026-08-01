"""Integration tests for the scheduled memory-consolidation job."""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.config.settings import AISettings, Settings
from app.infra.db.session import Database
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.repositories.memory import MemoryRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.scheduler import run_memory_consolidation
from app.services.memory import MemoryService
from httpx import ASGITransport

from tests.fake_anthropic.app import create_fake_anthropic_app


async def _seed_user(database: Database) -> User:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        return await UserRepository(session).add(
            User(
                tenant_id=tenant.id,
                google_subject=f"sub-{uuid.uuid4().hex[:8]}",
                email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            )
        )


@pytest.mark.asyncio
async def test_memory_consolidation_skips_when_ai_not_configured(
    database: Database,
) -> None:
    settings = Settings(environment="test", ai=AISettings(anthropic_api_key=""))
    consolidated = await run_memory_consolidation(database, settings)
    assert consolidated == 0


@pytest.mark.asyncio
async def test_memory_consolidation_summarizes_users_past_threshold(
    database: Database,
) -> None:
    user = await _seed_user(database)
    settings = Settings(
        environment="test",
        ai=AISettings(anthropic_api_key="test-key"),
    )
    settings.memory.summarization_threshold = 20

    async with database.session() as session:
        service = MemoryService(MemoryRepository(session))
        for i in range(20):
            await service.upsert(
                tenant_id=user.tenant_id,
                user_id=user.id,
                memory_type="fact",
                content=f"Observed fact number {i} about this user.",
                confidence=0.5,
            )

    fake_app = create_fake_anthropic_app()
    async with httpx.AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        consolidated = await run_memory_consolidation(
            database, settings, http_client=http_client
        )

    assert consolidated == 1

    async with database.session() as session:
        remaining = await MemoryRepository(session).list_by_type(user.id, "fact")
        assert len(remaining) == 1
        assert remaining[0].is_pinned is True
