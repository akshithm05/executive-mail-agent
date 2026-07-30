"""Label and EmailLabel repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models.label import EmailLabel, Label
from app.infra.repositories.base import SoftDeleteRepository, SQLAlchemyRepository


class LabelRepository(SoftDeleteRepository[Label]):
    """Persistence operations for mailbox labels."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Label)

    async def get_by_name(self, user_id: uuid.UUID, name: str) -> Label | None:
        """Return the label with the given name for this user, or ``None``."""
        stmt = select(Label).where(
            Label.user_id == user_id, Label.name == name, Label.deleted_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class EmailLabelRepository(SQLAlchemyRepository[EmailLabel]):
    """Persistence operations for email-label assignments.

    Not soft-delete-aware (unlike most repositories here): an assignment
    row represents current state, so removing a label from an email is a
    genuine hard delete of the association row. See
    :class:`~app.infra.models.label.EmailLabel`.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EmailLabel)

    async def list_by_email(self, email_id: uuid.UUID) -> Sequence[EmailLabel]:
        """Return all label assignments for an email."""
        stmt = select(EmailLabel).where(EmailLabel.email_id == email_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_assignment(
        self, email_id: uuid.UUID, label_id: uuid.UUID
    ) -> EmailLabel | None:
        """Return the assignment row for this (email, label) pair, if any."""
        stmt = select(EmailLabel).where(
            EmailLabel.email_id == email_id, EmailLabel.label_id == label_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def unassign(self, email_id: uuid.UUID, label_id: uuid.UUID) -> bool:
        """Remove a label from an email. Returns ``False`` if not assigned."""
        row = await self.get_assignment(email_id, label_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
