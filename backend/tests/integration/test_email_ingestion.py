"""Integration tests for the email ingestion pipeline.

Drives :class:`EmailIngestionService` against the real (SQLite-backed) test
database and the fake Gmail server (real HTTP, real MIME/base64 decoding) --
covering download+parse, the BeautifulSoup plain-text fallback, attachment
metadata storage, duplicate detection, the duplicate-insert race recovery
path, and event/queue publication.
"""

from __future__ import annotations

import uuid

import pytest
from app.config.settings import Settings
from app.infra.db.session import Database
from app.infra.events import EmailIngestedEvent, EventBus
from app.infra.google.gmail_client import GmailClient
from app.infra.google.rate_limiter import TokenBucketRateLimiter
from app.infra.models.email import Email
from app.infra.models.tenant import Tenant
from app.infra.models.user import User
from app.infra.queue import AIProcessingJob, AIProcessingQueue
from app.infra.repositories.attachment import AttachmentRepository
from app.infra.repositories.email import EmailRepository
from app.infra.repositories.tenant import TenantRepository
from app.infra.repositories.user import UserRepository
from app.services.email_ingestion_service import EmailIngestionService
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fake_google.app import GOOGLE_SUBJECT, FakeGoogleState

_ACCESS_TOKEN = "test-ingestion-access-token"


async def _seed_user(session: AsyncSession) -> User:
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


def _build_service(
    session: AsyncSession,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
    settings: Settings,
    event_bus: EventBus,
    ai_queue: AIProcessingQueue,
) -> EmailIngestionService:
    fake_google_state.access_tokens[_ACCESS_TOKEN] = GOOGLE_SUBJECT
    gmail_client = GmailClient(
        fake_google_http_client,
        settings.gmail,
        _ACCESS_TOKEN,
        TokenBucketRateLimiter(rate_per_second=1000.0, burst_capacity=1000),
    )
    return EmailIngestionService(
        gmail_client=gmail_client,
        email_repo=EmailRepository(session),
        attachment_repo=AttachmentRepository(session),
        event_bus=event_bus,
        ai_queue=ai_queue,
        db_session=session,
    )


@pytest.mark.asyncio
async def test_ingest_message_stores_email_attachment_event_and_job(
    database: Database,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
    settings: Settings,
) -> None:
    event_bus = EventBus()
    received_events: list[EmailIngestedEvent] = []

    async def on_ingested(event: EmailIngestedEvent) -> None:
        received_events.append(event)

    event_bus.subscribe(EmailIngestedEvent, on_ingested)
    ai_queue = AIProcessingQueue()

    async with database.session() as session:
        user = await _seed_user(session)
        service = _build_service(
            session,
            fake_google_http_client,
            fake_google_state,
            settings,
            event_bus,
            ai_queue,
        )

        email = await service.ingest_message(user, "msg-2")

        assert email.subject == "Invoice #1042"
        assert email.from_address == "Billing <billing@example.com>"
        assert email.body_text == "Please find the invoice attached."
        assert email.body_html == "<p>Please find the invoice attached.</p>"

        stored = await session.get(Email, email.id)
        assert stored is not None

        attachments = await AttachmentRepository(session).list_by_email(email.id)
        assert len(attachments) == 1
        assert attachments[0].filename == "invoice-1042.pdf"
        assert attachments[0].gmail_attachment_id == "att-1042"

    assert len(received_events) == 1
    assert received_events[0].gmail_message_id == "msg-2"
    assert received_events[0].email_id == email.id

    assert ai_queue.qsize() == 1
    job = await ai_queue.dequeue()
    assert isinstance(job, AIProcessingJob)
    assert job.email_id == email.id


@pytest.mark.asyncio
async def test_ingest_message_derives_plain_text_from_html_only_body(
    database: Database,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
    settings: Settings,
) -> None:
    async with database.session() as session:
        user = await _seed_user(session)
        service = _build_service(
            session,
            fake_google_http_client,
            fake_google_state,
            settings,
            EventBus(),
            AIProcessingQueue(),
        )

        email = await service.ingest_message(user, "msg-3")

        assert email.body_html is not None
        assert "<script>" in email.body_html  # raw HTML preserved as-is
        # Plain text is BeautifulSoup-derived: script content and tags gone.
        assert email.body_text == "Big Sale Save 20% today."


@pytest.mark.asyncio
async def test_ingest_message_is_idempotent_for_the_same_gmail_message_id(
    database: Database,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
    settings: Settings,
) -> None:
    ai_queue = AIProcessingQueue()
    event_bus = EventBus()
    publish_count = {"n": 0}

    async def counter(_event: EmailIngestedEvent) -> None:
        publish_count["n"] += 1

    event_bus.subscribe(EmailIngestedEvent, counter)

    async with database.session() as session:
        user = await _seed_user(session)
        service = _build_service(
            session,
            fake_google_http_client,
            fake_google_state,
            settings,
            event_bus,
            ai_queue,
        )

        first = await service.ingest_message(user, "msg-1")
        second = await service.ingest_message(user, "msg-1")

        assert first.id == second.id
        assert await EmailRepository(session).count() == 1

    assert publish_count["n"] == 1  # only the first ingestion published
    assert ai_queue.qsize() == 1  # only the first ingestion enqueued a job


@pytest.mark.asyncio
async def test_ingest_recovers_from_concurrent_duplicate_insert_race(
    database: Database,
    fake_google_http_client: AsyncClient,
    fake_google_state: FakeGoogleState,
    settings: Settings,
) -> None:
    """Simulate two workers racing to ingest the same message.

    ``ingest_message``'s upfront duplicate check cannot catch a true
    concurrent race (both check "not found" before either inserts). This
    uses two genuinely separate sessions/transactions -- exactly how two
    concurrent workers would each have their own request/job-scoped session
    -- so that rolling back the second (failed) transaction cannot also
    undo the first writer's already-committed row.
    """
    async with database.session() as session:
        user = await _seed_user(session)
        service = _build_service(
            session,
            fake_google_http_client,
            fake_google_state,
            settings,
            EventBus(),
            AIProcessingQueue(),
        )
        first = await service.ingest_message(user, "msg-1")
        first_id, user_id = first.id, user.id

    async with database.session() as session:
        second_user = await UserRepository(session).get(user_id)
        assert second_user is not None
        service = _build_service(
            session,
            fake_google_http_client,
            fake_google_state,
            settings,
            EventBus(),
            AIProcessingQueue(),
        )

        # Bypass the upfront duplicate check to simulate a second worker
        # that already checked "not found" before the first writer committed.
        second = await service._ingest_once(
            second_user.id, second_user.tenant_id, "msg-1"
        )

        assert second.id == first_id
        assert await EmailRepository(session).count() == 1
