"""Integration test: the readiness probe reports Redis status informationally."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_readiness_reports_redis_without_gating_overall_status(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["database"] == "up"
    # The fake Redis in tests always answers ping() -- see tests/fake_redis.py.
    assert body["checks"]["redis"] == "up"
    assert body["status"] == "ok"
