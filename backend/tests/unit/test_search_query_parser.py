"""Unit tests for the heuristic (no-AI) search query parser."""

from __future__ import annotations

from app.services.search_query_parser import heuristic_parse


def test_unread_sets_is_read_false() -> None:
    result = heuristic_parse("Unread invoices")
    assert result.is_read is False
    assert result.semantic_query == "Unread invoices"


def test_read_without_unread_sets_is_read_true() -> None:
    result = heuristic_parse("read emails from last week")
    assert result.is_read is True


def test_no_read_signal_leaves_is_read_null() -> None:
    result = heuristic_parse("recruiter emails")
    assert result.is_read is None


def test_last_month_sets_days_back() -> None:
    result = heuristic_parse("Placement emails last month")
    assert result.days_back == 60


def test_this_week_sets_days_back() -> None:
    result = heuristic_parse("emails this week")
    assert result.days_back == 7


def test_yesterday_sets_days_back() -> None:
    result = heuristic_parse("what came in yesterday")
    assert result.days_back == 2


def test_no_date_phrase_leaves_days_back_null() -> None:
    result = heuristic_parse("internship offers")
    assert result.days_back is None


def test_heuristic_never_extracts_category_or_keyword() -> None:
    # These require real language understanding -- the heuristic path
    # leaves them for embedding similarity instead of guessing.
    result = heuristic_parse("Emails mentioning Deloitte")
    assert result.category is None
    assert result.keyword is None
    assert result.semantic_query == "Emails mentioning Deloitte"


def test_low_confidence_reflects_the_fallback_nature() -> None:
    result = heuristic_parse("anything")
    assert result.confidence < 0.5
