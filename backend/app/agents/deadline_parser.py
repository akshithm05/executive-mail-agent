"""Deterministic deadline-phrase recognizer.

Complements (does not replace) the LLM-based ``deadline_detection`` graph
node: this module recognizes a fixed set of common deadline phrasings via
regex and resolves them to an absolute UTC datetime against a reference
"received at" time -- zero LLM calls, fully deterministic, and unit-testable
with plain datetime math. Recognized forms:

* Explicit dates -- ISO (``2026-08-01``), numeric (``8/1/2026``), or
  ``Month Day[, Year]`` (``August 1``, ``Aug 1st, 2026``).
* ``within N hours``/``within N days``.
* ``EOD``/``end of day``/``COB``/``close of business``, optionally combined
  with a weekday (``EOD Friday``).
* ``tomorrow``.
* A bare weekday name (``Friday``) -- always resolves to the *next*
  occurrence strictly after the reference date, never the same day, since a
  deadline phrased as a future weekday is never referring to "right now".
* ``next week`` -- the coming Monday.

The graph feeds this parser's result into the ``deadline_detection`` node's
prompt as a hint (see ``app/agents/graph.py``); it is a second, independent
signal alongside the LLM's own free-form extraction, not a replacement for
it -- most real deadlines are phrased in ways no fixed pattern list covers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

_END_OF_BUSINESS_HOUR = 17  # 5pm UTC -- used whenever only a *day* is implied.

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_ISO_DATE_PATTERN = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_DATE_PATTERN = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_MONTH_DAY_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b"
)
_WITHIN_PATTERN = re.compile(r"\bwithin\s+(\d+)\s*(hours?|hrs?|days?)\b")
_EOD_PATTERN = re.compile(r"\b(eod|end of day|cob|close of business)\b")
_WEEKDAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
)
_TOMORROW_PATTERN = re.compile(r"\btomorrow\b")
_NEXT_WEEK_PATTERN = re.compile(r"\bnext week\b")


@dataclass(frozen=True, slots=True)
class DeadlineMatch:
    """One recognized deadline phrase, resolved to an absolute datetime."""

    phrase: str
    deadline_at: datetime
    pattern: str


def _ensure_aware(reference: datetime) -> datetime:
    return reference if reference.tzinfo is not None else reference.replace(tzinfo=UTC)


def _end_of_day(anchor_date: date) -> datetime:
    return datetime.combine(anchor_date, time(hour=_END_OF_BUSINESS_HOUR)).replace(
        tzinfo=UTC
    )


def _next_weekday_date(from_date: date, target_weekday: int) -> date:
    """Return the next date matching ``target_weekday``, strictly after ``from_date``.

    A bare weekday mention ("by Friday") always means a future occurrence --
    if ``from_date`` itself is a Friday, this returns the Friday *one week*
    later, not the same day.
    """
    days_ahead = (target_weekday - from_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return from_date + timedelta(days=days_ahead)


def _match_explicit_date(text: str, reference: datetime) -> DeadlineMatch | None:
    iso_match = _ISO_DATE_PATTERN.search(text)
    if iso_match:
        year, month, day = (int(g) for g in iso_match.groups())
        return _build_explicit_match(iso_match.group(0), year, month, day)

    numeric_match = _NUMERIC_DATE_PATTERN.search(text)
    if numeric_match:
        month, day, year = (int(g) for g in numeric_match.groups())
        if year < 100:
            year += 2000
        return _build_explicit_match(numeric_match.group(0), year, month, day)

    month_match = _MONTH_DAY_PATTERN.search(text)
    if month_match:
        month = _MONTHS[month_match.group(1)]
        day = int(month_match.group(2))
        year_group = month_match.group(3)
        try:
            if year_group:
                year = int(year_group)
            else:
                year = reference.year
                if date(year, month, day) < reference.date():
                    year += 1
        except ValueError:
            return None
        return _build_explicit_match(month_match.group(0), year, month, day)

    return None


def _build_explicit_match(
    phrase: str, year: int, month: int, day: int
) -> DeadlineMatch | None:
    try:
        anchor_date = date(year, month, day)
    except ValueError:
        return None
    return DeadlineMatch(
        phrase=phrase, deadline_at=_end_of_day(anchor_date), pattern="explicit_date"
    )


def _match_within(text: str, reference: datetime) -> DeadlineMatch | None:
    match = _WITHIN_PATTERN.search(text)
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    delta = timedelta(hours=amount) if unit.startswith("h") else timedelta(days=amount)
    return DeadlineMatch(
        phrase=match.group(0), deadline_at=reference + delta, pattern="within"
    )


def _match_eod_or_cob(text: str, reference: datetime) -> DeadlineMatch | None:
    eod_match = _EOD_PATTERN.search(text)
    if eod_match is None:
        return None
    weekday_match = _WEEKDAY_PATTERN.search(text)
    if weekday_match:
        anchor_date = _next_weekday_date(
            reference.date(), _WEEKDAYS[weekday_match.group(1)]
        )
        phrase = f"{eod_match.group(0)} {weekday_match.group(0)}"
    else:
        anchor_date = reference.date()
        phrase = eod_match.group(0)
    return DeadlineMatch(
        phrase=phrase, deadline_at=_end_of_day(anchor_date), pattern="eod_cob"
    )


def _match_tomorrow(text: str, reference: datetime) -> DeadlineMatch | None:
    match = _TOMORROW_PATTERN.search(text)
    if match is None:
        return None
    anchor_date = reference.date() + timedelta(days=1)
    return DeadlineMatch(
        phrase=match.group(0), deadline_at=_end_of_day(anchor_date), pattern="tomorrow"
    )


def _match_weekday(text: str, reference: datetime) -> DeadlineMatch | None:
    match = _WEEKDAY_PATTERN.search(text)
    if match is None:
        return None
    anchor_date = _next_weekday_date(reference.date(), _WEEKDAYS[match.group(1)])
    return DeadlineMatch(
        phrase=match.group(0), deadline_at=_end_of_day(anchor_date), pattern="weekday"
    )


def _match_next_week(text: str, reference: datetime) -> DeadlineMatch | None:
    match = _NEXT_WEEK_PATTERN.search(text)
    if match is None:
        return None
    anchor_date = _next_weekday_date(reference.date(), 0)  # Monday
    return DeadlineMatch(
        phrase=match.group(0),
        deadline_at=_end_of_day(anchor_date),
        pattern="next_week",
    )


# Checked in priority order: an explicit calendar date is the least
# ambiguous signal, then a precise "within N hours/days" window, then the
# increasingly coarse day-level phrasings.
_RECOGNIZERS = (
    _match_explicit_date,
    _match_within,
    _match_eod_or_cob,
    _match_tomorrow,
    _match_weekday,
    _match_next_week,
)


def parse_deadline(text: str, *, reference: datetime) -> DeadlineMatch | None:
    """Scan ``text`` for the first recognized deadline phrase.

    Args:
        text: Email subject/body to scan (case-insensitive).
        reference: The point in time phrases are resolved relative to --
            normally the email's ``received_at``. Must be timezone-aware or
            naive-and-implicitly-UTC.

    Returns:
        The highest-priority recognized match, or ``None`` if nothing in
        the fixed phrase set was found.
    """
    reference = _ensure_aware(reference)
    lowered = text.lower()
    for recognizer in _RECOGNIZERS:
        match = recognizer(lowered, reference)
        if match is not None:
            return match
    return None


def format_hint(match: DeadlineMatch) -> str:
    """Render a recognized match as a prompt hint for the deadline_detection node."""
    return (
        f'A rule-based scan found the deadline phrase "{match.phrase}", which '
        f"resolves to {match.deadline_at.isoformat()} (UTC). Verify this against "
        "the email's actual meaning before using it -- override it if the text "
        "clearly means something else."
    )
