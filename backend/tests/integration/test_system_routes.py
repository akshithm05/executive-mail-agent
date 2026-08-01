"""Integration tests for the operational endpoints: /metrics and the DLQ.

``/metrics`` assertions check for known metric *names* rather than exact
values -- the underlying Prometheus registry (see ``app/infra/metrics.py``)
is a process-wide singleton shared across the whole test session, so
absolute counter values are not meaningful to assert on here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.infra.db.session import Database
from app.infra.models.failed_job import FailedJob
from app.infra.models.tenant import Tenant
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from httpx import AsyncClient

from tests.fake_google.app import USER_EMAIL


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_text_format(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "aeea_job_runs_total" in body
    assert "aeea_health_check_status" in body
    assert "aeea_retry_queue_depth" in body
    assert "aeea_dead_letter_queue_depth" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_requires_no_authentication(client: AsyncClient) -> None:
    # Unlike every other route in this API, /metrics follows Prometheus
    # scrape convention and is deliberately unauthenticated.
    response = await client.get("/api/v1/metrics")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_failed_jobs_route_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/system/failed-jobs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_failed_jobs_route_lists_the_users_tenant_jobs(
    logged_in_client: AsyncClient, database: Database
) -> None:
    async with database.session() as session:
        user = await UserRepository(session).get_by_email(USER_EMAIL)
        assert user is not None
        await FailedJobRepository(session).add(
            FailedJob(
                tenant_id=user.tenant_id,
                user_id=user.id,
                job_type="email_ingestion",
                payload={"message_id": "msg-1"},
                error_message="timed out",
                status="dead_letter",
                next_attempt_at=datetime.now(UTC),
            )
        )
        # A job belonging to a different tenant must never appear.
        other_tenant = await TenantRepository(session).add(
            Tenant(name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
        )
        await FailedJobRepository(session).add(
            FailedJob(
                tenant_id=other_tenant.id,
                job_type="email_ingestion",
                payload={},
                error_message="unrelated",
                status="dead_letter",
                next_attempt_at=datetime.now(UTC),
            )
        )

    response = await logged_in_client.get(
        "/api/v1/system/failed-jobs", params={"status": "dead_letter"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["job_type"] == "email_ingestion"
    assert body[0]["error_message"] == "timed out"
