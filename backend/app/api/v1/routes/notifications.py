"""Notification endpoints: listing and marking as read."""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUserDep, NotificationServiceDep
from app.core.exceptions import NotFoundError
from app.infra.models.notification import Notification
from app.schemas.notification import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _get_owned_notification(
    notification_id: uuid.UUID, user: CurrentUserDep, service: NotificationServiceDep
) -> Notification:
    """Fetch a notification, scoped to the current user (404 if not theirs)."""
    notification = await service.get(notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFoundError("No notification with this id was found.")
    return notification


OwnedNotificationDep = Annotated[Notification, Depends(_get_owned_notification)]


@router.get("", response_model=list[NotificationRead], summary="List notifications")
async def list_notifications(
    user: CurrentUserDep,
    service: NotificationServiceDep,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[NotificationRead]:
    """List the current user's notifications, most recent first."""
    notifications = await service.list_by_user(
        user.id, unread_only=unread_only, limit=limit, offset=offset
    )
    return [NotificationRead.model_validate(n) for n in notifications]


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark a notification read",
)
async def mark_notification_read(
    notification: OwnedNotificationDep, service: NotificationServiceDep
) -> NotificationRead:
    """Mark a notification as read."""
    updated = await service.mark_read(notification.id)
    return NotificationRead.model_validate(cast(Notification, updated))
