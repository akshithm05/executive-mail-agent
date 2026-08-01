"""Renders an :class:`~app.services.analytics.AnalyticsReport` as CSV or PDF.

Both renderers are pure functions over an already-computed report -- no
database access here, so they're trivially unit-testable and reusable from
anywhere (an API route today, a scheduled "email me my weekly report" job
later) without re-running the underlying aggregation queries.
"""

from __future__ import annotations

import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.analytics import AnalyticsReport

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        (
            "ROWBACKGROUNDS",
            (0, 1),
            (-1, -1),
            [colors.white, colors.HexColor("#f9fafb")],
        ),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
)


def _fmt_hours(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_csv(report: AnalyticsReport) -> str:
    """Render a multi-section CSV report -- one table per chart, blank-line separated.

    Not "tidy data" for programmatic re-ingestion (each section has its own
    columns) -- this is an executive report export, meant to be opened in a
    spreadsheet, not piped into another system.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["AI Executive Email Assistant -- Analytics Report"])
    writer.writerow(["Generated at", report.generated_at.isoformat()])
    writer.writerow(["Range (days)", report.range_days])
    writer.writerow([])

    writer.writerow(["Daily Email Volume"])
    writer.writerow(["Date", "Count"])
    for daily_point in report.daily_email_volume:
        writer.writerow([daily_point.period.isoformat(), daily_point.count])
    writer.writerow([])

    writer.writerow(["Weekly Email Volume"])
    writer.writerow(["Week Starting", "Count"])
    for weekly_point in report.weekly_email_volume:
        writer.writerow([weekly_point.period.isoformat(), weekly_point.count])
    writer.writerow([])

    writer.writerow(["Monthly Trends"])
    writer.writerow(["Month", "Email Count", "Task Count", "Avg Priority Score"])
    for month_point in report.monthly_trends:
        writer.writerow(
            [
                month_point.month.isoformat(),
                month_point.email_count,
                month_point.task_count,
                f"{month_point.avg_priority_score:.2f}"
                if month_point.avg_priority_score is not None
                else "",
            ]
        )
    writer.writerow([])

    writer.writerow(["Category Distribution"])
    writer.writerow(["Category", "Count"])
    for category_row in report.category_distribution:
        writer.writerow([category_row.category, category_row.count])
    writer.writerow([])

    writer.writerow(["Priority Distribution"])
    writer.writerow(["Band", "Count"])
    for priority_row in report.priority_distribution:
        writer.writerow([priority_row.band, priority_row.count])
    writer.writerow([])

    writer.writerow(["Response Time"])
    writer.writerow(["Average (hours)", "Median (hours)", "Sample Size"])
    writer.writerow(
        [
            _fmt_hours(report.response_time.average_hours),
            _fmt_hours(report.response_time.median_hours),
            report.response_time.sample_size,
        ]
    )
    writer.writerow([])

    writer.writerow(["Unread Summary"])
    writer.writerow(["Total Unread", report.unread_summary.total_unread])
    writer.writerow(["By Category"])
    writer.writerow(["Category", "Count"])
    for unread_category_row in report.unread_summary.by_category:
        writer.writerow([unread_category_row.category, unread_category_row.count])
    writer.writerow(["By Age"])
    writer.writerow(["Age Band", "Count"])
    for age_row in report.unread_summary.by_age:
        writer.writerow([age_row.band, age_row.count])
    writer.writerow([])

    writer.writerow(["Task Completion"])
    writer.writerow(["Total Tasks", report.task_completion.total_tasks])
    writer.writerow(["Completed Tasks", report.task_completion.completed_tasks])
    writer.writerow(
        ["Completion Rate", _fmt_pct(report.task_completion.completion_rate)]
    )
    writer.writerow(["By Priority"])
    writer.writerow(["Priority", "Total", "Completed"])
    for priority_breakdown_row in report.task_completion.by_priority:
        writer.writerow(
            [
                priority_breakdown_row.priority,
                priority_breakdown_row.total,
                priority_breakdown_row.completed,
            ]
        )

    return buffer.getvalue()


def render_pdf(report: AnalyticsReport) -> bytes:
    """Render a structured PDF report.

    Tables, not chart images -- see the module docstring.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    story: list[object] = [
        Paragraph("AI Executive Email Assistant — Analytics Report", styles["Title"]),
        Paragraph(
            f"Generated {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')} "
            f"&middot; last {report.range_days} days",
            styles["Normal"],
        ),
        Spacer(1, 0.25 * inch),
    ]

    def add_table(title: str, header: list[str], rows: list[list[str]]) -> None:
        story.append(Paragraph(title, styles["Heading2"]))
        if not rows:
            story.append(Paragraph("No data in this range.", styles["Normal"]))
        else:
            table = Table([header, *rows], hAlign="LEFT")
            table.setStyle(_TABLE_STYLE)
            story.append(table)
        story.append(Spacer(1, 0.2 * inch))

    add_table(
        "Daily Email Volume",
        ["Date", "Count"],
        [[p.period.isoformat(), str(p.count)] for p in report.daily_email_volume],
    )
    add_table(
        "Weekly Email Volume",
        ["Week Starting", "Count"],
        [[p.period.isoformat(), str(p.count)] for p in report.weekly_email_volume],
    )
    add_table(
        "Monthly Trends",
        ["Month", "Emails", "Tasks", "Avg Priority"],
        [
            [
                p.month.isoformat(),
                str(p.email_count),
                str(p.task_count),
                f"{p.avg_priority_score:.2f}"
                if p.avg_priority_score is not None
                else "n/a",
            ]
            for p in report.monthly_trends
        ],
    )
    add_table(
        "Category Distribution",
        ["Category", "Count"],
        [[r.category, str(r.count)] for r in report.category_distribution],
    )
    add_table(
        "Priority Distribution",
        ["Band", "Count"],
        [[r.band, str(r.count)] for r in report.priority_distribution],
    )
    add_table(
        "Response Time",
        ["Average (hours)", "Median (hours)", "Sample Size"],
        [
            [
                _fmt_hours(report.response_time.average_hours),
                _fmt_hours(report.response_time.median_hours),
                str(report.response_time.sample_size),
            ]
        ],
    )
    add_table(
        "Unread — By Category",
        ["Category", "Count"],
        [[r.category, str(r.count)] for r in report.unread_summary.by_category],
    )
    add_table(
        "Unread — By Age",
        ["Age Band", "Count"],
        [[r.band, str(r.count)] for r in report.unread_summary.by_age],
    )
    add_table(
        "Task Completion",
        ["Total Tasks", "Completed", "Completion Rate"],
        [
            [
                str(report.task_completion.total_tasks),
                str(report.task_completion.completed_tasks),
                _fmt_pct(report.task_completion.completion_rate),
            ]
        ],
    )
    add_table(
        "Task Completion — By Priority",
        ["Priority", "Total", "Completed"],
        [
            [r.priority, str(r.total), str(r.completed)]
            for r in report.task_completion.by_priority
        ],
    )

    doc.build(story)
    return buffer.getvalue()
