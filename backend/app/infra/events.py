"""In-process domain event bus.

A minimal publish/subscribe mechanism so pipeline stages (ingestion, future
triage/drafting) can react to what happened without being directly wired
together. This is in-process only -- events do not survive a process
restart and are not shared across replicas. A multi-instance deployment
should replace this with a real broker (e.g. Redis Streams, SQS); the
``EventBus`` interface is kept narrow enough that swapping the
implementation later does not require touching publishers or subscribers.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base type for all events published on the bus."""

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class EmailIngestedEvent(DomainEvent):
    """Published once a Gmail message has been mirrored locally."""

    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID = field(default_factory=uuid.uuid4)
    email_id: uuid.UUID = field(default_factory=uuid.uuid4)
    gmail_message_id: str = ""


Subscriber = Callable[[DomainEvent], Awaitable[None]]


class EventBus:
    """A minimal async, in-process publish/subscribe bus.

    Subscribers are looked up by the exact event class, so subscribing to
    ``DomainEvent`` itself does not receive subclass events -- register per
    concrete event type.
    """

    def __init__(self) -> None:
        self._subscribers: dict[type[Any], list[Subscriber]] = {}

    def subscribe(self, event_type: type[DomainEvent], handler: Subscriber) -> None:
        """Register ``handler`` to be called for every ``event_type`` published."""
        self._subscribers.setdefault(event_type, []).append(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Call every subscriber registered for this event's exact type.

        A failing subscriber is logged and does not prevent other
        subscribers from running, and never propagates back to the
        publisher -- publishing an event must not fail the operation that
        triggered it (e.g. email ingestion succeeding but a notification
        handler erroring).
        """
        handlers = self._subscribers.get(type(event), [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "event_subscriber_failed",
                    event_type=type(event).__name__,
                    handler=getattr(handler, "__qualname__", repr(handler)),
                )
