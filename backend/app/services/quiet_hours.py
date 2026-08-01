"""Quiet-hours evaluation: a local-time window that defers channel delivery.

See the module docstring on
``app/infra/models/notification_quiet_hours.py`` for the schema. The window
is defined in the user's own timezone and supports an overnight wrap (e.g.
22:00 -> 07:00, where the window spans midnight).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config.logging import get_logger
from app.core.time import as_naive_utc, utcnow
from app.infra.models.notification_quiet_hours import NotificationQuietHours
from app.infra.repositories.notification_quiet_hours import (
    NotificationQuietHoursRepository,
)

logger = get_logger(__name__)

# `Notification.type` values urgent enough to bypass quiet hours when
# `allow_urgent_override` is set -- deliberately narrower than the rule
# engine's "important" set (see `app/services/notification_rules.py`):
# a draft being ready can wait until morning, a high-priority email can't.
URGENT_NOTIFICATION_TYPES = frozenset({"high_priority_email"})


def _resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("quiet_hours_unknown_timezone", timezone=name)
        return ZoneInfo("UTC")


def _local_time_at(config: NotificationQuietHours, at: datetime) -> datetime:
    """Convert ``at`` (naive UTC) to an aware datetime in ``config``'s timezone."""
    aware_utc = as_naive_utc(at).replace(tzinfo=UTC)
    return aware_utc.astimezone(_resolve_timezone(config.timezone))


def _time_in_window(current: time, start: time, end: time) -> bool:
    if start == end:
        # Zero-width window is ambiguous configuration -- treat as "never
        # quiet" rather than risk silently suppressing every notification.
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end  # overnight wrap


def is_within_quiet_hours(
    config: NotificationQuietHours, at: datetime | None = None
) -> bool:
    """Return True if ``at`` (default now) is inside ``config``'s quiet-hours window."""
    if not config.is_enabled:
        return False
    moment = at if at is not None else utcnow()
    local_dt = _local_time_at(config, moment)
    return _time_in_window(local_dt.time(), config.start_time, config.end_time)


def is_urgent(notification_type: str) -> bool:
    """Return True if a notification of this type bypasses quiet hours by default."""
    return notification_type in URGENT_NOTIFICATION_TYPES


def next_quiet_hours_end(
    config: NotificationQuietHours, at: datetime | None = None
) -> datetime:
    """Return the naive-UTC instant the current quiet-hours window ends.

    Callers should only call this when ``is_within_quiet_hours`` is already
    True for ``at`` -- it returns the *next* occurrence of ``end_time``,
    which is meaningless outside the window.
    """
    moment = at if at is not None else utcnow()
    local_dt = _local_time_at(config, moment)
    tz = local_dt.tzinfo
    end_local = datetime.combine(local_dt.date(), config.end_time, tzinfo=tz)
    if end_local <= local_dt:
        end_local += timedelta(days=1)
    return as_naive_utc(end_local.astimezone(UTC))


class NotificationQuietHoursService:
    """CRUD for a user's (singleton) quiet-hours configuration."""

    def __init__(self, repository: NotificationQuietHoursRepository) -> None:
        self._repo = repository

    async def get_by_user(self, user_id: uuid.UUID) -> NotificationQuietHours | None:
        """Return a user's quiet-hours config, or ``None`` if never configured."""
        return await self._repo.get_by_user(user_id)

    async def set(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        is_enabled: bool,
        start_time: time,
        end_time: time,
        timezone: str,
        allow_urgent_override: bool,
    ) -> NotificationQuietHours:
        """Create or update (upsert) a user's quiet-hours configuration."""
        existing = await self._repo.get_by_user(user_id)
        if existing is not None:
            updated = await self._repo.update_fields(
                existing.id,
                is_enabled=is_enabled,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                allow_urgent_override=allow_urgent_override,
            )
            return cast(NotificationQuietHours, updated)
        return await self._repo.add(
            NotificationQuietHours(
                tenant_id=tenant_id,
                user_id=user_id,
                is_enabled=is_enabled,
                start_time=start_time,
                end_time=end_time,
                timezone=timezone,
                allow_urgent_override=allow_urgent_override,
            )
        )
