"""Notification CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.infra.models.notification import Notification
from app.infra.repositories.notification import NotificationRepository
from app.services.crud import CRUDService


class NotificationService(CRUDService[Notification]):
    """CRUD operations for in-app notifications."""

    def __init__(self, repository: NotificationRepository) -> None:
        super().__init__(repository)
        self._repo: NotificationRepository = repository

    async def list_unread(self, user_id: uuid.UUID) -> Sequence[Notification]:
        """Return a user's unread notifications, most recent first."""
        return await self._repo.list_unread(user_id)

    async def mark_read(self, notification_id: uuid.UUID) -> Notification | None:
        """Mark a notification as read."""
        return await self._repo.mark_read(notification_id)
