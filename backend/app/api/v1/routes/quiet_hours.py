"""Quiet-hours configuration endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, NotificationQuietHoursServiceDep
from app.schemas.quiet_hours import QuietHoursRead, QuietHoursUpdate

router = APIRouter(prefix="/quiet-hours", tags=["quiet-hours"])


@router.get("", response_model=QuietHoursRead | None, summary="Get quiet-hours config")
async def get_quiet_hours(
    user: CurrentUserDep, service: NotificationQuietHoursServiceDep
) -> QuietHoursRead | None:
    """Return the current user's quiet-hours config, or ``null`` if never set."""
    config = await service.get_by_user(user.id)
    return QuietHoursRead.model_validate(config) if config is not None else None


@router.put(
    "", response_model=QuietHoursRead, summary="Set quiet-hours config (upsert)"
)
async def set_quiet_hours(
    body: QuietHoursUpdate,
    user: CurrentUserDep,
    service: NotificationQuietHoursServiceDep,
) -> QuietHoursRead:
    """Create or update the current user's quiet-hours configuration."""
    config = await service.set(
        tenant_id=user.tenant_id,
        user_id=user.id,
        is_enabled=body.is_enabled,
        start_time=body.start_time,
        end_time=body.end_time,
        timezone=body.timezone,
        allow_urgent_override=body.allow_urgent_override,
    )
    return QuietHoursRead.model_validate(config)
