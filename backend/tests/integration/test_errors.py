"""Integration tests for the centralized error handling."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_unknown_route_returns_problem_json(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 404
    assert body["code"] == "not_found"
    assert "request_id" in body


@pytest.mark.asyncio
async def test_response_has_request_id_header(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health/live")
    assert resp.headers.get("X-Request-ID")


@pytest.mark.asyncio
async def test_inbound_request_id_is_echoed(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/health/live", headers={"X-Request-ID": "trace-123"}
    )
    assert resp.headers["X-Request-ID"] == "trace-123"
