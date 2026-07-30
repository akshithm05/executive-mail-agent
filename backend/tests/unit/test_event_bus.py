"""Tests for the in-process domain event bus."""

import uuid

import pytest
from app.infra.events import DomainEvent, EmailIngestedEvent, EventBus


@pytest.mark.asyncio
async def test_publish_calls_registered_subscriber() -> None:
    bus = EventBus()
    received: list[EmailIngestedEvent] = []

    async def handler(event: DomainEvent) -> None:
        assert isinstance(event, EmailIngestedEvent)
        received.append(event)

    bus.subscribe(EmailIngestedEvent, handler)
    event = EmailIngestedEvent(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        gmail_message_id="msg-1",
    )
    await bus.publish(event)

    assert received == [event]


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_does_nothing() -> None:
    bus = EventBus()
    # Should not raise even though nothing is subscribed.
    await bus.publish(EmailIngestedEvent())


@pytest.mark.asyncio
async def test_failing_subscriber_does_not_propagate_or_block_others() -> None:
    bus = EventBus()
    calls: list[str] = []

    async def failing_handler(_event: DomainEvent) -> None:
        calls.append("failing")
        raise RuntimeError("boom")

    async def healthy_handler(_event: DomainEvent) -> None:
        calls.append("healthy")

    bus.subscribe(EmailIngestedEvent, failing_handler)
    bus.subscribe(EmailIngestedEvent, healthy_handler)

    await bus.publish(EmailIngestedEvent())  # must not raise

    assert calls == ["failing", "healthy"]


@pytest.mark.asyncio
async def test_subscribers_are_matched_by_exact_event_type() -> None:
    bus = EventBus()
    calls: list[str] = []

    async def base_handler(_event: DomainEvent) -> None:
        calls.append("base")

    bus.subscribe(DomainEvent, base_handler)
    await bus.publish(EmailIngestedEvent())  # a DomainEvent subclass

    assert calls == []
