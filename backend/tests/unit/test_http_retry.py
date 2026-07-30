"""Tests for retry/backoff behavior against transient upstream failures.

Uses a minimal, purpose-built flaky ASGI app (not Google-shaped -- that's
what ``tests/fake_google`` is for) run over a real ``httpx.ASGITransport``, so
these assert genuine request counts and real elapsed wait times rather than
mocked call counts.
"""

from __future__ import annotations

import time

import pytest
from app.core.exceptions import RateLimitExceededError, UpstreamServiceError
from app.infra.google.http import send_with_retry
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

_URL = "http://flaky.test/flaky"


def _build_flaky_app(
    fail_times: int, fail_status: int, retry_after: str | None = None
) -> tuple[FastAPI, dict[str, int]]:
    app = FastAPI()
    state = {"remaining": fail_times, "calls": 0}

    @app.get("/flaky")
    async def flaky() -> Response:
        state["calls"] += 1
        if state["remaining"] > 0:
            state["remaining"] -= 1
            headers = {"Retry-After": retry_after} if retry_after else {}
            return Response(status_code=fail_status, headers=headers)
        return Response(
            status_code=200, content=b'{"ok": true}', media_type="application/json"
        )

    return app, state


@pytest.mark.asyncio
async def test_send_with_retry_recovers_after_transient_failures() -> None:
    app, state = _build_flaky_app(fail_times=2, fail_status=503)
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        response = await send_with_retry(client, "GET", _URL, max_attempts=5)

    assert response.status_code == 200
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_send_with_retry_exhausts_and_raises_rate_limit_error_for_429() -> None:
    app, state = _build_flaky_app(fail_times=10, fail_status=429)
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        with pytest.raises(RateLimitExceededError):
            await send_with_retry(client, "GET", _URL, max_attempts=2)

    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_send_with_retry_exhausts_and_raises_upstream_error_for_5xx() -> None:
    app, state = _build_flaky_app(fail_times=10, fail_status=500)
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        with pytest.raises(UpstreamServiceError):
            await send_with_retry(client, "GET", _URL, max_attempts=2)

    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_send_with_retry_honors_retry_after_seconds_header() -> None:
    app, _state = _build_flaky_app(fail_times=1, fail_status=429, retry_after="1")
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        start = time.monotonic()
        response = await send_with_retry(client, "GET", _URL, max_attempts=3)
        elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert elapsed >= 0.9  # honored the server's requested 1s delay, not a guess


@pytest.mark.asyncio
async def test_send_with_retry_does_not_retry_non_retryable_4xx() -> None:
    app, state = _build_flaky_app(fail_times=10, fail_status=404)
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        response = await send_with_retry(client, "GET", _URL, max_attempts=5)

    assert response.status_code == 404
    assert state["calls"] == 1  # no retry attempted for a non-retryable status
