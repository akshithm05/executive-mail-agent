"""Integration tests for the health endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_ok_when_database_up(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "up"


@pytest.mark.asyncio
async def test_readiness_degraded_when_database_down(
    client: AsyncClient, app: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail() -> bool:
        return False

    monkeypatch.setattr(app.state.db, "ping", _fail)  # type: ignore[attr-defined]
    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "down"
