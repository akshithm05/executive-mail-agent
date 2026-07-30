"""Integration tests for the repository pattern."""

import uuid

import pytest
from app.infra.db.session import Database
from app.infra.models.tenant import Tenant
from app.infra.repositories.tenant import TenantRepository


@pytest.mark.asyncio
async def test_tenant_crud_roundtrip(database: Database) -> None:
    async with database.session() as session:
        repo = TenantRepository(session)
        tenant = await repo.add(Tenant(name="Acme", slug="acme", plan="pro"))
        tenant_id = tenant.id

    async with database.session() as session:
        repo = TenantRepository(session)
        fetched = await repo.get(tenant_id)
        assert fetched is not None
        assert fetched.name == "Acme"
        assert fetched.plan == "pro"

        by_slug = await repo.get_by_slug("acme")
        assert by_slug is not None
        assert by_slug.id == tenant_id

        assert await repo.count() == 1


@pytest.mark.asyncio
async def test_tenant_get_missing_returns_none(database: Database) -> None:
    async with database.session() as session:
        repo = TenantRepository(session)
        assert await repo.get(uuid.uuid4()) is None
        assert await repo.get_by_slug("nope") is None


@pytest.mark.asyncio
async def test_tenant_delete(database: Database) -> None:
    async with database.session() as session:
        repo = TenantRepository(session)
        tenant = await repo.add(Tenant(name="Beta", slug="beta"))
        tenant_id = tenant.id

    async with database.session() as session:
        repo = TenantRepository(session)
        assert await repo.delete(tenant_id) is True
        assert await repo.delete(tenant_id) is False
