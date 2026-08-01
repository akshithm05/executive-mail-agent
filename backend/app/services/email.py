"""Email CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.infra.models.email import Email
from app.infra.repositories.email import EmailRepository
from app.services.crud import CRUDService


class EmailService(CRUDService[Email]):
    """CRUD operations for emails, plus mailbox-specific queries."""

    def __init__(self, repository: EmailRepository) -> None:
        super().__init__(repository)
        self._repo: EmailRepository = repository

    async def get_by_gmail_message_id(
        self, user_id: uuid.UUID, gmail_message_id: str
    ) -> Email | None:
        """Return the email with the given Gmail message id for this user."""
        return await self._repo.get_by_gmail_message_id(user_id, gmail_message_id)

    async def list_by_thread(
        self, user_id: uuid.UUID, gmail_thread_id: str
    ) -> Sequence[Email]:
        """Return all emails in a thread, oldest first."""
        return await self._repo.list_by_thread(user_id, gmail_thread_id)

    async def list_unread(
        self, user_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Email]:
        """Return unread emails for a user, most recent first."""
        return await self._repo.list_unread(user_id, limit=limit, offset=offset)

    async def mark_read(self, email_id: uuid.UUID) -> Email | None:
        """Mark an email as read."""
        return await self.update(email_id, is_read=True)

    async def list_for_dashboard(
        self,
        user_id: uuid.UUID,
        *,
        category: str | None = None,
        is_read: bool | None = None,
        has_deadline: bool | None = None,
        sort: str = "recent",
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Email]:
        """Return a user's emails, filtered/sorted for dashboard views."""
        return await self._repo.list_by_user(
            user_id,
            category=category,
            is_read=is_read,
            has_deadline=has_deadline,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    async def list_urgent(
        self, user_id: uuid.UUID, *, limit: int = 10
    ) -> Sequence[Email]:
        """Return the most urgent emails for a user."""
        return await self._repo.list_urgent(user_id, limit=limit)

    async def list_upcoming_deadlines(
        self, user_id: uuid.UUID, *, limit: int = 10
    ) -> Sequence[Email]:
        """Return emails with a future deadline, soonest first."""
        return await self._repo.list_upcoming_deadlines(
            user_id, now=datetime.now(UTC), limit=limit
        )
