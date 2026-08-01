"""Unit tests for quiet-hours window evaluation."""

from __future__ import annotations

import uuid
from datetime import datetime, time

from app.infra.models.notification_quiet_hours import NotificationQuietHours
from app.services.quiet_hours import (
    is_urgent,
    is_within_quiet_hours,
    next_quiet_hours_end,
)


def _config(**overrides: object) -> NotificationQuietHours:
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "is_enabled": True,
        "start_time": time(22, 0),
        "end_time": time(7, 0),
        "timezone": "UTC",
        "allow_urgent_override": True,
    }
    defaults.update(overrides)
    return NotificationQuietHours(**defaults)  # type: ignore[arg-type]


def test_disabled_is_never_within_quiet_hours() -> None:
    config = _config(is_enabled=False)
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 23, 0)) is False


def test_non_overnight_window() -> None:
    config = _config(start_time=time(9, 0), end_time=time(17, 0))
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 12, 0)) is True
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 8, 59)) is False
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 17, 0)) is False


def test_overnight_window_wraps_past_midnight() -> None:
    config = _config(start_time=time(22, 0), end_time=time(7, 0))
    # Late at night, before midnight.
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 23, 30)) is True
    # Early morning, after midnight but before the end time.
    assert is_within_quiet_hours(config, datetime(2026, 1, 2, 3, 0)) is True
    # Midday: well outside the window either way.
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 12, 0)) is False


def test_zero_width_window_is_never_quiet() -> None:
    config = _config(start_time=time(9, 0), end_time=time(9, 0))
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 9, 0)) is False


def test_timezone_conversion() -> None:
    # 02:00 UTC is 21:00 the prior day in America/New_York (UTC-5 in Jan),
    # which is inside a 20:00 -> 23:00 local-time window.
    config = _config(
        start_time=time(20, 0), end_time=time(23, 0), timezone="America/New_York"
    )
    assert is_within_quiet_hours(config, datetime(2026, 1, 2, 2, 0)) is True
    assert is_within_quiet_hours(config, datetime(2026, 1, 2, 12, 0)) is False


def test_unknown_timezone_falls_back_to_utc_instead_of_raising() -> None:
    config = _config(
        start_time=time(9, 0), end_time=time(17, 0), timezone="Not/A_Real_Zone"
    )
    assert is_within_quiet_hours(config, datetime(2026, 1, 1, 12, 0)) is True


def test_next_quiet_hours_end_overnight_rolls_to_next_day() -> None:
    config = _config(start_time=time(22, 0), end_time=time(7, 0))
    end = next_quiet_hours_end(config, datetime(2026, 1, 1, 23, 30))
    assert end == datetime(2026, 1, 2, 7, 0)


def test_next_quiet_hours_end_after_midnight_stays_same_day() -> None:
    config = _config(start_time=time(22, 0), end_time=time(7, 0))
    end = next_quiet_hours_end(config, datetime(2026, 1, 2, 3, 0))
    assert end == datetime(2026, 1, 2, 7, 0)


def test_is_urgent_only_true_for_high_priority_email() -> None:
    assert is_urgent("high_priority_email") is True
    assert is_urgent("draft_ready") is False
    assert is_urgent("reminder") is False
