"""Dashboard summary response schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PriorityHeatmapCell(BaseModel):
    """One (category, priority band) cell of the priority heatmap."""

    category: str
    priority_band: str = Field(description='e.g. "60-80" (priority_score percent).')
    count: int


class DashboardSummaryResponse(BaseModel):
    """Aggregate counts and chart data for the overview dashboard."""

    total_emails: int
    unread_emails: int
    urgent_emails: int
    upcoming_deadlines: int
    pending_tasks: int
    pending_drafts: int
    unread_notifications: int
    category_counts: dict[str, int]
    priority_heatmap: list[PriorityHeatmapCell]
