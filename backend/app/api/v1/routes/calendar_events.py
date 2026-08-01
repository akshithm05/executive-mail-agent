"""Calendar event endpoints: the dashboard's upcoming-agenda view.

Read-only -- events are created by the email-triage graph's
``calendar_suggestion`` node and pushed to Google Calendar by
``app/services/calendar_sync_service.py``; this route just lists them.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CalendarEventServiceDep, CurrentUserDep
from app.schemas.calendar_event import CalendarEventRead

router = APIRouter(prefix="/calendar-events", tags=["calendar-events"])


@router.get("", response_model=list[CalendarEventRead], summary="List upcoming events")
async def list_upcoming_events(
    user: CurrentUserDep,
    service: CalendarEventServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CalendarEventRead]:
    """List the current user's upcoming (not cancelled) calendar events."""
    events = await service.list_upcoming(user.id, limit=limit)
    return [CalendarEventRead.model_validate(e) for e in events]
