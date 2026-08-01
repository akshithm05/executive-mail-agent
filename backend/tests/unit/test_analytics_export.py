"""Unit tests for the CSV/PDF analytics report renderers."""

from __future__ import annotations

from datetime import date, datetime

from app.services.analytics import (
    AnalyticsReport,
    CategoryCount,
    MonthlyTrendPoint,
    PriorityBandCount,
    ResponseTimeStats,
    TaskCompletionStats,
    TaskPriorityBreakdown,
    TimeSeriesPoint,
    UnreadAgeBandCount,
    UnreadSummary,
)
from app.services.analytics_export import render_csv, render_pdf


def _sample_report() -> AnalyticsReport:
    return AnalyticsReport(
        generated_at=datetime(2026, 7, 31, 12, 0, 0),
        range_days=30,
        daily_email_volume=[
            TimeSeriesPoint(period=date(2026, 7, 30), count=3),
            TimeSeriesPoint(period=date(2026, 7, 31), count=5),
        ],
        weekly_email_volume=[TimeSeriesPoint(period=date(2026, 7, 27), count=8)],
        monthly_trends=[
            MonthlyTrendPoint(
                month=date(2026, 7, 1),
                email_count=8,
                task_count=2,
                avg_priority_score=0.62,
            )
        ],
        category_distribution=[
            CategoryCount(category="fyi", count=4),
            CategoryCount(category="action_required", count=2),
        ],
        priority_distribution=[
            PriorityBandCount(band="0-20", count=1),
            PriorityBandCount(band="80-100", count=2),
        ],
        response_time=ResponseTimeStats(
            average_hours=3.5, median_hours=2.0, sample_size=4
        ),
        unread_summary=UnreadSummary(
            total_unread=6,
            by_category=[CategoryCount(category="newsletter", count=3)],
            by_age=[UnreadAgeBandCount(band="<1 day", count=6)],
        ),
        task_completion=TaskCompletionStats(
            total_tasks=10,
            completed_tasks=7,
            completion_rate=0.7,
            daily_completions=[TimeSeriesPoint(period=date(2026, 7, 31), count=2)],
            by_priority=[TaskPriorityBreakdown(priority="high", total=4, completed=3)],
        ),
    )


def test_render_csv_includes_every_section() -> None:
    csv_text = render_csv(_sample_report())
    assert "Daily Email Volume" in csv_text
    assert "Weekly Email Volume" in csv_text
    assert "Monthly Trends" in csv_text
    assert "Category Distribution" in csv_text
    assert "Priority Distribution" in csv_text
    assert "Response Time" in csv_text
    assert "Unread Summary" in csv_text
    assert "Task Completion" in csv_text
    assert "fyi" in csv_text
    assert "2026-07-31" in csv_text


def test_render_csv_handles_empty_sections_without_error() -> None:
    empty = AnalyticsReport(
        generated_at=datetime(2026, 7, 31, 12, 0, 0),
        range_days=7,
        daily_email_volume=[],
        weekly_email_volume=[],
        monthly_trends=[],
        category_distribution=[],
        priority_distribution=[],
        response_time=ResponseTimeStats(
            average_hours=None, median_hours=None, sample_size=0
        ),
        unread_summary=UnreadSummary(total_unread=0, by_category=[], by_age=[]),
        task_completion=TaskCompletionStats(
            total_tasks=0, completed_tasks=0, completion_rate=0.0
        ),
    )
    csv_text = render_csv(empty)
    assert "n/a" in csv_text  # empty average/median response time
    assert "Task Completion" in csv_text


def test_render_pdf_produces_a_valid_pdf_document() -> None:
    pdf_bytes = render_pdf(_sample_report())
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_render_pdf_handles_empty_sections_without_error() -> None:
    empty = AnalyticsReport(
        generated_at=datetime(2026, 7, 31, 12, 0, 0),
        range_days=7,
        daily_email_volume=[],
        weekly_email_volume=[],
        monthly_trends=[],
        category_distribution=[],
        priority_distribution=[],
        response_time=ResponseTimeStats(
            average_hours=None, median_hours=None, sample_size=0
        ),
        unread_summary=UnreadSummary(total_unread=0, by_category=[], by_age=[]),
        task_completion=TaskCompletionStats(
            total_tasks=0, completed_tasks=0, completion_rate=0.0
        ),
    )
    pdf_bytes = render_pdf(empty)
    assert pdf_bytes.startswith(b"%PDF")
