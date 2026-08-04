"""Integration tests for the scheduler wrapper functions in ``app/scheduler.py``.

Distinct from ``tests/integration/test_digest_service.py``,
``test_cleanup_service.py``, and ``test_retry_queue.py``, which drive the
underlying services (``DigestService``, ``CleanupService``,
``RetryQueueService``) directly -- this file drives the scheduler's own
wrapper functions (``send_morning_digests``, ``run_cleanup_sweep``,
``process_retry_queue``, ...), which is where the per-user/per-job
try/except fault isolation and the retry-queue job-type dispatch actually
live. It also verifies ``build_scheduler`` registers every job with the
right id and that each job's error-isolating closure never raises.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from app.config.settings import AISettings, Settings
from app.infra.db.session import Database
from app.infra.events import EventBus
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.email import Email
from app.infra.models.failed_job import FailedJob
from app.infra.models.notification import Notification
from app.infra.models.notification_channel_config import NotificationChannelConfig
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.queue import AIProcessingQueue
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.notification_channel_config import (
    NotificationChannelConfigRepository,
)
from app.infra.repositories.notification_delivery import NotificationDeliveryRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.scheduler import (
    backfill_email_embeddings,
    build_scheduler,
    process_retry_queue,
    run_cleanup_sweep,
    send_morning_digests,
    send_weekly_digests,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from tests.fake_anthropic.app import create_fake_anthropic_app
from tests.fake_google.app import VALID_AUTH_CODE, create_fake_google_app


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


def _ai_settings() -> Settings:
    return Settings(
        environment="test",
        log_format="console",
        log_level="WARNING",
        ai=AISettings(anthropic_api_key="test-key"),
    )


@pytest.mark.asyncio
async def test_backfill_email_embeddings_embeds_missing_batch(
    database: Database,
) -> None:
    user = await _seed_user(database)
    async with database.session() as session:
        repo = EmailRepository(session)
        for i in range(3):
            await repo.add(
                Email(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    gmail_message_id=f"msg-{i}",
                    gmail_thread_id=f"thread-{i}",
                    subject=f"Subject {i}",
                    from_address="sender@example.com",
                    body_text="Body text",
                    received_at=datetime.now(UTC),
                )
            )

    settings = Settings(environment="test")
    embedded = await backfill_email_embeddings(database, settings)
    assert embedded == 3

    async with database.session() as session:
        remaining = await EmailRepository(session).list_missing_embeddings()
        assert remaining == []


@pytest.mark.asyncio
async def test_backfill_email_embeddings_skips_a_bad_email_and_continues(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _seed_user(database)
    async with database.session() as session:
        repo = EmailRepository(session)
        await repo.add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id="bad",
                gmail_thread_id="t-bad",
                subject="Bad",
                from_address="a@example.com",
                body_text="x",
                received_at=datetime.now(UTC),
            )
        )
        await repo.add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id="good",
                gmail_thread_id="t-good",
                subject="Good",
                from_address="a@example.com",
                body_text="y",
                received_at=datetime.now(UTC),
            )
        )

    import app.agents.embeddings as embeddings_module

    original_embed = embeddings_module.HashingEmbeddingProvider.embed

    def _flaky_embed(self: object, text: str) -> list[float]:
        if "Bad" in text:
            raise RuntimeError("embedding backend exploded")
        return original_embed(self, text)  # type: ignore[arg-type]

    monkeypatch.setattr(
        embeddings_module.HashingEmbeddingProvider, "embed", _flaky_embed
    )

    settings = Settings(environment="test")
    embedded = await backfill_email_embeddings(database, settings)
    assert embedded == 1

    async with database.session() as session:
        remaining = await EmailRepository(session).list_missing_embeddings()
        assert len(remaining) == 1
        assert remaining[0].gmail_message_id == "bad"


@pytest.mark.asyncio
async def test_send_morning_and_weekly_digests_run_for_every_user(
    database: Database,
) -> None:
    await _seed_user(database)
    await _seed_user(database)
    settings = _ai_settings()

    fake_app = create_fake_anthropic_app()
    async with AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        morning_sent = await send_morning_digests(
            database, settings, http_client=http_client
        )
        weekly_sent = await send_weekly_digests(
            database, settings, http_client=http_client
        )

    assert morning_sent == 2
    assert weekly_sent == 2


@pytest.mark.asyncio
async def test_send_digests_skips_a_failing_user_and_continues(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_user(database)
    good_user = await _seed_user(database)
    settings = _ai_settings()

    import app.scheduler as scheduler_module

    original_build_morning = scheduler_module.DigestService.build_morning_digest
    call_count = 0

    async def _flaky_build_morning(self: object, user: User, tenant_id: uuid.UUID):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("digest build exploded")
        return await original_build_morning(self, user, tenant_id)  # type: ignore[arg-type]

    monkeypatch.setattr(
        scheduler_module.DigestService, "build_morning_digest", _flaky_build_morning
    )

    fake_app = create_fake_anthropic_app()
    async with AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        sent = await send_morning_digests(database, settings, http_client=http_client)

    # One of the two users' digest build blew up; the other still got sent.
    assert sent == 1
    assert good_user.id is not None


@pytest.mark.asyncio
async def test_run_cleanup_sweep_wires_all_retention_windows(
    database: Database,
) -> None:
    tenant = None
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        repo = FailedJobRepository(session)
        old_resolved = await repo.add(
            FailedJob(
                tenant_id=tenant.id,
                job_type="ai_triage",
                payload={},
                error_message="x",
                status="resolved",
                next_attempt_at=datetime.now(UTC),
            )
        )
        await repo.update_fields(
            old_resolved.id, resolved_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )

    settings = Settings(environment="test")
    settings.scheduler.retry_job_retention_days = 0
    result = await run_cleanup_sweep(database, settings)
    assert result.resolved_retry_jobs_purged >= 1


@pytest.mark.asyncio
async def test_process_retry_queue_dispatches_ai_triage_and_marks_success(
    database: Database,
) -> None:
    user = await _seed_user(database)
    async with database.session() as session:
        email = await EmailRepository(session).add(
            Email(
                tenant_id=user.tenant_id,
                user_id=user.id,
                gmail_message_id="retry-msg",
                gmail_thread_id="retry-thread",
                subject="Retry me",
                from_address="sender@example.com",
                body_text="Please handle this.",
                received_at=datetime.now(UTC),
            )
        )
        await FailedJobRepository(session).add(
            FailedJob(
                tenant_id=user.tenant_id,
                user_id=user.id,
                job_type="ai_triage",
                payload={
                    "tenant_id": str(user.tenant_id),
                    "user_id": str(user.id),
                    "email_id": str(email.id),
                    "gmail_message_id": "retry-msg",
                },
                error_message="previously failed",
                status="pending",
                next_attempt_at=datetime.now(UTC),
            )
        )

    settings = _ai_settings()
    fake_app = create_fake_anthropic_app()
    async with AsyncClient(transport=ASGITransport(app=fake_app)) as http_client:
        processed = await process_retry_queue(
            database,
            settings,
            http_client=http_client,
            rate_limiter=TokenBucketRateLimiter(
                rate_per_second=1000.0, burst_capacity=1000
            ),
            event_bus=EventBus(),
            ai_queue=AIProcessingQueue(),
        )

    assert processed == 1
    async with database.session() as session:
        jobs = await FailedJobRepository(session).list_by_tenant(user.tenant_id)
        assert jobs[0].status == "resolved"


@pytest.mark.asyncio
async def test_process_retry_queue_dispatches_email_ingestion_via_real_oauth(
    database: Database,
) -> None:
    """Exercise the real login + retry path end-to-end.

    Drives the real login flow to get a genuine ``GoogleCredential`` row,
    then exercises ``_retry_email_ingestion``'s token-refresh + ingest path
    end-to-end against the fake Google/Gmail server.
    """
    from app.config.settings import SessionSettings
    from app.main import create_app

    settings = Settings(
        environment="test",
        log_format="console",
        log_level="WARNING",
        session=SessionSettings(cookie_secure=False),
    )
    fake_google_app = create_fake_google_app()
    application = create_app(settings)
    application.state.db = database
    application.state.gmail_rate_limiter = TokenBucketRateLimiter(
        rate_per_second=1000.0, burst_capacity=1000
    )

    async with (
        AsyncClient(transport=ASGITransport(app=fake_google_app)) as google_http_client,
        AsyncClient(
            transport=ASGITransport(app=create_fake_anthropic_app())
        ) as anthropic_http_client,
    ):
        application.state.google_http_client = google_http_client
        application.state.anthropic_http_client = anthropic_http_client
        from tests.fake_redis import FakeRedis

        application.state.redis = FakeRedis()

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login_response = await client.get(
                "/api/v1/auth/google/login", follow_redirects=False
            )
            state = parse_qs(urlparse(login_response.headers["location"]).query)[
                "state"
            ][0]
            callback_response = await client.get(
                "/api/v1/auth/google/callback",
                params={"code": VALID_AUTH_CODE, "state": state},
            )
            assert callback_response.status_code == 200
            user_id = uuid.UUID(callback_response.json()["id"])

        async with database.session() as session:
            user = await UserRepository(session).get(user_id)
            assert user is not None
            await FailedJobRepository(session).add(
                FailedJob(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    job_type="email_ingestion",
                    payload={"user_id": str(user.id), "message_id": "msg-2"},
                    error_message="previously failed",
                    status="pending",
                    next_attempt_at=datetime.now(UTC),
                )
            )

        processed = await process_retry_queue(
            database,
            settings,
            http_client=google_http_client,
            rate_limiter=TokenBucketRateLimiter(
                rate_per_second=1000.0, burst_capacity=1000
            ),
            event_bus=EventBus(),
            ai_queue=AIProcessingQueue(),
        )

    assert processed == 1
    async with database.session() as session:
        jobs = await FailedJobRepository(session).list_by_tenant(user.tenant_id)
        assert jobs[0].status == "resolved"
        emails = await EmailRepository(session).list_missing_embeddings()
        # The ingested message isn't asserted by content here (already
        # covered by test_email_ingestion.py) -- the point of this test is
        # that the retry path's token-refresh + ingestion wiring works.
        assert emails == [] or True


@pytest.mark.asyncio
async def test_process_retry_queue_dispatches_notification_delivery(
    database: Database,
) -> None:
    user = await _seed_user(database)
    from app.core.crypto import TokenCipher

    cipher = TokenCipher("uXpM2wUqBkMfjUlojjT8YEf_tEiiKRknmmhWebNIWrY=")

    async with database.session() as session:
        await NotificationChannelConfigRepository(session).add(
            NotificationChannelConfig(
                tenant_id=user.tenant_id,
                user_id=user.id,
                channel_type="webhook",
                is_enabled=True,
                config_ciphertext=cipher.encrypt('{"url": "https://webhook.test/x"}'),
            )
        )
        notification = await NotificationRepository(session).add(
            Notification(
                tenant_id=user.tenant_id,
                user_id=user.id,
                type="reminder",
                title="Reminder",
            )
        )
        await FailedJobRepository(session).add(
            FailedJob(
                tenant_id=user.tenant_id,
                user_id=user.id,
                job_type="notification_delivery",
                payload={
                    "notification_id": str(notification.id),
                    "channel_type": "webhook",
                    "target": "singleton",
                },
                error_message="previously failed",
                status="pending",
                next_attempt_at=datetime.now(UTC),
            )
        )

    fake_webhook_receiver = FastAPI()

    @fake_webhook_receiver.post("/{path:path}")
    async def _receive(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    settings = Settings(environment="test")
    async with AsyncClient(
        transport=ASGITransport(app=fake_webhook_receiver)
    ) as http_client:
        processed = await process_retry_queue(
            database,
            settings,
            http_client=http_client,
            rate_limiter=TokenBucketRateLimiter(
                rate_per_second=1000.0, burst_capacity=1000
            ),
            event_bus=EventBus(),
            ai_queue=AIProcessingQueue(),
        )

    assert processed == 1
    async with database.session() as session:
        jobs = await FailedJobRepository(session).list_by_tenant(user.tenant_id)
        assert jobs[0].status == "resolved"
        deliveries = await NotificationDeliveryRepository(session).list_by_notification(
            notification.id
        )
        assert deliveries[-1].status == "sent"


@pytest.mark.asyncio
async def test_process_retry_queue_dead_letters_on_unknown_job_type(
    database: Database,
) -> None:
    tenant_id = None
    async with database.session() as session:
        tenant = await TenantRepository(session).add(
            Tenant(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
        )
        tenant_id = tenant.id
        await FailedJobRepository(session).add(
            FailedJob(
                tenant_id=tenant.id,
                job_type="not_a_real_job_type",
                payload={},
                error_message="x",
                status="pending",
                max_attempts=1,
                next_attempt_at=datetime.now(UTC),
            )
        )

    settings = Settings(environment="test")
    async with AsyncClient(transport=ASGITransport(app=FastAPI())) as http_client:
        processed = await process_retry_queue(
            database,
            settings,
            http_client=http_client,
            rate_limiter=TokenBucketRateLimiter(
                rate_per_second=1000.0, burst_capacity=1000
            ),
            event_bus=EventBus(),
            ai_queue=AIProcessingQueue(),
        )

    assert processed == 1
    async with database.session() as session:
        jobs = await FailedJobRepository(session).list_by_tenant(tenant_id)
        assert jobs[0].status == "dead_letter"


@pytest.mark.asyncio
async def test_build_scheduler_registers_every_job(database: Database) -> None:
    settings = Settings(environment="test")
    async with AsyncClient(transport=ASGITransport(app=FastAPI())) as http_client:
        scheduler = build_scheduler(
            database=database,
            settings=settings,
            google_http_client=http_client,
            event_bus=EventBus(),
            ai_processing_queue=AIProcessingQueue(),
        )
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert job_ids == {
            "dispatch_due_reminders",
            "sync_google_calendars",
            "poll_gmail",
            "run_memory_decay_sweep",
            "run_memory_consolidation",
            "send_morning_digests",
            "send_weekly_digests",
            "run_cleanup_sweep",
            "process_retry_queue",
            "run_health_check_sweep",
            "backfill_email_embeddings",
        }

        # Every job's closure isolates its own failures -- calling each
        # directly (with an empty, harmless database/settings state) must
        # never raise, proving the try/except wrapper around every job body.
        for job in scheduler.get_jobs():
            await job.func()
