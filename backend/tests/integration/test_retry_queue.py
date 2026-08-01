"""Integration tests for the retry queue / dead-letter queue.

Drives :class:`RetryQueueService` against a real (SQLite-backed) database.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from app.core.time import utcnow
from app.infra.db.session import Database
from app.infra.models.tenant import Tenant
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.tenant import TenantRepository
from app.services.retry_queue import RetryQueueService


async def _seed_tenant(database: Database) -> uuid.UUID:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        return tenant.id


@pytest.mark.asyncio
async def test_enqueue_failure_schedules_a_near_term_retry(database: Database) -> None:
    tenant_id = await _seed_tenant(database)

    async with database.session() as session:
        service = RetryQueueService(FailedJobRepository(session))
        job = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="email_ingestion",
            payload={"message_id": "msg-1"},
            error=RuntimeError("boom"),
        )

    assert job.status == "pending"
    assert job.attempt_count == 1
    assert job.max_attempts == 5
    now = utcnow()
    assert now < job.next_attempt_at <= now + timedelta(seconds=35)


@pytest.mark.asyncio
async def test_record_success_resolves_the_job(database: Database) -> None:
    tenant_id = await _seed_tenant(database)

    async with database.session() as session:
        service = RetryQueueService(FailedJobRepository(session))
        job = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="ai_triage",
            payload={},
            error="boom",
        )
        await service.record_success(job)

    async with database.session() as session:
        repo = FailedJobRepository(session)
        refreshed = await repo.get(job.id)
        assert refreshed is not None
        assert refreshed.status == "resolved"
        assert refreshed.resolved_at is not None


@pytest.mark.asyncio
async def test_record_failure_reschedules_until_max_attempts_then_dead_letters(
    database: Database,
) -> None:
    tenant_id = await _seed_tenant(database)

    async with database.session() as session:
        service = RetryQueueService(FailedJobRepository(session))
        job = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="ai_triage",
            payload={},
            error="first failure",
            max_attempts=3,
        )
        # Attempt 2 of 3: still pending, rescheduled further out.
        await service.record_failure(job, "second failure")

    async with database.session() as session:
        repo = FailedJobRepository(session)
        job = await repo.get(job.id)
        assert job is not None
        assert job.status == "pending"
        assert job.attempt_count == 2

    async with database.session() as session:
        service = RetryQueueService(FailedJobRepository(session))
        # Attempt 3 of 3: exhausted -- dead-lettered.
        await service.record_failure(job, "third failure")

    async with database.session() as session:
        repo = FailedJobRepository(session)
        job = await repo.get(job.id)
        assert job is not None
        assert job.status == "dead_letter"
        assert job.attempt_count == 3
        assert job.error_message == "third failure"


@pytest.mark.asyncio
async def test_list_due_only_returns_jobs_whose_next_attempt_has_passed(
    database: Database,
) -> None:
    tenant_id = await _seed_tenant(database)

    async with database.session() as session:
        repo = FailedJobRepository(session)
        service = RetryQueueService(repo)
        due_job = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="ai_triage",
            payload={},
            error="x",
        )
        # Force it into the past so it counts as due.
        await repo.update_fields(
            due_job.id, next_attempt_at=utcnow() - timedelta(seconds=1)
        )
        future_job = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="ai_triage",
            payload={},
            error="y",
        )

    async with database.session() as session:
        service = RetryQueueService(FailedJobRepository(session))
        due = await service.list_due()

    due_ids = {job.id for job in due}
    assert due_job.id in due_ids
    assert future_job.id not in due_ids


@pytest.mark.asyncio
async def test_purge_resolved_older_than_only_removes_stale_resolved_rows(
    database: Database,
) -> None:
    tenant_id = await _seed_tenant(database)

    async with database.session() as session:
        repo = FailedJobRepository(session)
        service = RetryQueueService(repo)
        stale_resolved = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="ai_triage",
            payload={},
            error="x",
        )
        await service.record_success(stale_resolved)
        await repo.update_fields(
            stale_resolved.id, updated_at=utcnow() - timedelta(days=60)
        )

        fresh_resolved = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="ai_triage",
            payload={},
            error="y",
        )
        await service.record_success(fresh_resolved)

        still_pending = await service.enqueue_failure(
            tenant_id=tenant_id,
            user_id=None,
            job_type="ai_triage",
            payload={},
            error="z",
        )
        await repo.update_fields(
            still_pending.id, next_attempt_at=utcnow() - timedelta(days=60)
        )

    async with database.session() as session:
        service = RetryQueueService(FailedJobRepository(session))
        purged = await service.purge_resolved_older_than(retention_days=30)

    assert purged == 1

    async with database.session() as session:
        repo = FailedJobRepository(session)
        assert await repo.get(stale_resolved.id) is None
        assert await repo.get(fresh_resolved.id) is not None
        assert await repo.get(still_pending.id) is not None
