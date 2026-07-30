"""Unit tests for the deterministic deadline-phrase recognizer."""

from __future__ import annotations

from datetime import UTC, datetime

from app.agents.deadline_parser import format_hint, parse_deadline

# A fixed Thursday reference point so weekday/relative-phrase math is
# deterministic across test runs.
_REFERENCE = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


def test_no_deadline_phrase_returns_none() -> None:
    assert parse_deadline("Just wanted to say hi.", reference=_REFERENCE) is None


def test_tomorrow() -> None:
    match = parse_deadline("Please send this tomorrow.", reference=_REFERENCE)
    assert match is not None
    assert match.pattern == "tomorrow"
    assert match.deadline_at == datetime(2026, 7, 31, 17, 0, tzinfo=UTC)


def test_bare_weekday_resolves_to_next_occurrence() -> None:
    match = parse_deadline("We need this by Friday.", reference=_REFERENCE)
    assert match is not None
    assert match.pattern == "weekday"
    assert match.deadline_at == datetime(2026, 7, 31, 17, 0, tzinfo=UTC)


def test_bare_weekday_on_same_weekday_rolls_to_next_week() -> None:
    """Reference is a Thursday; mentioning "Thursday" means the *next* one."""
    match = parse_deadline("Let's confirm on Thursday.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 8, 6, 17, 0, tzinfo=UTC)


def test_within_hours() -> None:
    match = parse_deadline("Please reply within 48 hours.", reference=_REFERENCE)
    assert match is not None
    assert match.pattern == "within"
    assert match.deadline_at == datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def test_within_days() -> None:
    match = parse_deadline("Get this done within 2 days please.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def test_eod() -> None:
    match = parse_deadline("Send it EOD.", reference=_REFERENCE)
    assert match is not None
    assert match.pattern == "eod_cob"
    assert match.deadline_at == datetime(2026, 7, 30, 17, 0, tzinfo=UTC)


def test_end_of_day_phrase() -> None:
    match = parse_deadline("Need this by end of day.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 7, 30, 17, 0, tzinfo=UTC)


def test_cob_combined_with_weekday() -> None:
    match = parse_deadline("Need this COB Friday.", reference=_REFERENCE)
    assert match is not None
    assert match.pattern == "eod_cob"
    assert match.deadline_at == datetime(2026, 7, 31, 17, 0, tzinfo=UTC)


def test_close_of_business_phrase() -> None:
    match = parse_deadline(
        "Please close of business today would be great.", reference=_REFERENCE
    )
    assert match is not None
    assert match.deadline_at == datetime(2026, 7, 30, 17, 0, tzinfo=UTC)


def test_next_week() -> None:
    match = parse_deadline("Let's sync next week.", reference=_REFERENCE)
    assert match is not None
    assert match.pattern == "next_week"
    assert match.deadline_at == datetime(2026, 8, 3, 17, 0, tzinfo=UTC)


def test_iso_date() -> None:
    match = parse_deadline("The deadline is 2026-08-15.", reference=_REFERENCE)
    assert match is not None
    assert match.pattern == "explicit_date"
    assert match.deadline_at == datetime(2026, 8, 15, 17, 0, tzinfo=UTC)


def test_numeric_date() -> None:
    match = parse_deadline("Due date: 8/1/2026.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 8, 1, 17, 0, tzinfo=UTC)


def test_numeric_date_two_digit_year() -> None:
    match = parse_deadline("Due date: 8/1/26.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 8, 1, 17, 0, tzinfo=UTC)


def test_month_day_this_year() -> None:
    match = parse_deadline("Please respond by August 15.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 8, 15, 17, 0, tzinfo=UTC)


def test_month_day_with_ordinal_suffix() -> None:
    match = parse_deadline("Please respond by August 1st.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 8, 1, 17, 0, tzinfo=UTC)


def test_month_day_in_the_past_rolls_to_next_year() -> None:
    """A month/day mentioned in late July that's already passed rolls to next year."""
    match = parse_deadline("Please respond by March 5.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2027, 3, 5, 17, 0, tzinfo=UTC)


def test_month_day_with_explicit_year() -> None:
    match = parse_deadline("Please respond by March 5, 2026.", reference=_REFERENCE)
    assert match is not None
    assert match.deadline_at == datetime(2026, 3, 5, 17, 0, tzinfo=UTC)


def test_explicit_date_takes_priority_over_weekday_mention() -> None:
    """Both an explicit date and a weekday are present -- the date wins."""
    match = parse_deadline(
        "By Friday, or at the latest 2026-08-20.", reference=_REFERENCE
    )
    assert match is not None
    assert match.pattern == "explicit_date"


def test_within_takes_priority_over_bare_weekday() -> None:
    match = parse_deadline(
        "Within 24 hours, ideally before Friday.", reference=_REFERENCE
    )
    assert match is not None
    assert match.pattern == "within"


def test_naive_reference_is_treated_as_utc() -> None:
    naive_reference = datetime(2026, 7, 30, 10, 0)
    match = parse_deadline("Please respond tomorrow.", reference=naive_reference)
    assert match is not None
    assert match.deadline_at.tzinfo is not None


def test_invalid_calendar_date_is_not_matched() -> None:
    # February 30th does not exist -- must not crash, must not match.
    assert parse_deadline("Due by February 30.", reference=_REFERENCE) is None


def test_format_hint_includes_phrase_and_resolved_datetime() -> None:
    match = parse_deadline("Please respond tomorrow.", reference=_REFERENCE)
    assert match is not None
    hint = format_hint(match)
    assert "tomorrow" in hint
    assert match.deadline_at.isoformat() in hint
