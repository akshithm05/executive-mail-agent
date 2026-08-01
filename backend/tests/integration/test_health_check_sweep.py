"""Integration tests for the scheduled health-check sweep.

Distinct from the on-demand ``/health/*`` HTTP probes (see
``tests/integration/test_health.py``) -- this drives
:func:`run_health_check_sweep` directly and inspects the Prometheus gauges
it sets.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.config.settings import Settings
from app.infra.db.session import Database
from app.infra.metrics import HEALTH_CHECK_STATUS
from app.infra.models.failed_job import FailedJob
from app.infra.models.tenant import Tenant
from app.infra.queue import AIProcessingJob, AIProcessingQueue
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.tenant import TenantRepository
from app.scheduler import run_health_check_sweep


def _job() -> AIProcessingJob:
    return AIProcessingJob(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        gmail_message_id="x",
    )


@pytest.mark.asyncio
async def test_health_check_sweep_reports_healthy_by_default(
    database: Database, settings: Settings
) -> None:
    healthy = await run_health_check_sweep(
        database, settings, ai_processing_queue=AIProcessingQueue()
    )
    assert healthy is True
    assert HEALTH_CHECK_STATUS.labels(check="database")._value.get() == 1.0
    assert HEALTH_CHECK_STATUS.labels(check="ai_processing_queue")._value.get() == 1.0
    assert HEALTH_CHECK_STATUS.labels(check="dead_letter_queue")._value.get() == 1.0


@pytest.mark.asyncio
async def test_health_check_sweep_flags_a_deep_ai_processing_queue(
    database: Database, settings: Settings
) -> None:
    queue = AIProcessingQueue()
    for _ in range(settings.scheduler.ai_processing_queue_warning_depth + 1):
        await queue.enqueue(_job())

    healthy = await run_health_check_sweep(
        database, settings, ai_processing_queue=queue
    )
    assert healthy is False
    assert HEALTH_CHECK_STATUS.labels(check="ai_processing_queue")._value.get() == 0.0


@pytest.mark.asyncio
async def test_health_check_sweep_flags_a_deep_dead_letter_queue(
    database: Database, settings: Settings
) -> None:
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        repo = FailedJobRepository(session)
        for _ in range(settings.scheduler.dead_letter_queue_warning_depth + 1):
            await repo.add(
                FailedJob(
                    tenant_id=tenant.id,
                    job_type="ai_triage",
                    payload={},
                    error_message="boom",
                    status="dead_letter",
                    next_attempt_at=datetime.now(UTC),
                )
            )

    healthy = await run_health_check_sweep(
        database, settings, ai_processing_queue=AIProcessingQueue()
    )
    assert healthy is False
    assert HEALTH_CHECK_STATUS.labels(check="dead_letter_queue")._value.get() == 0.0
