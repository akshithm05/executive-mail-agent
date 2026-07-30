"""Integration test for the version endpoint."""

import pytest
from app import __version__
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_version_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == __version__
    assert body["environment"] == "test"
    assert body["name"]
