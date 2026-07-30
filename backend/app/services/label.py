"""Label CRUD service, plus email-label assignment operations."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.core.exceptions import ConflictError
from app.infra.models.label import EmailLabel, Label
from app.infra.repositories.label import EmailLabelRepository, LabelRepository
from app.services.crud import CRUDService


class LabelService(CRUDService[Label]):
    """CRUD operations for labels, plus assigning/unassigning them on emails."""

    def __init__(
        self, repository: LabelRepository, email_label_repository: EmailLabelRepository
    ) -> None:
        super().__init__(repository)
        self._repo: LabelRepository = repository
        self._email_labels = email_label_repository

    async def get_by_name(self, user_id: uuid.UUID, name: str) -> Label | None:
        """Return a user's label by name, or ``None``."""
        return await self._repo.get_by_name(user_id, name)

    async def assign(self, email_id: uuid.UUID, label_id: uuid.UUID) -> EmailLabel:
        """Apply a label to an email.

        Raises:
            ConflictError: The label is already applied to this email.
        """
        existing = await self._email_labels.get_assignment(email_id, label_id)
        if existing is not None:
            raise ConflictError("This label is already applied to this email.")
        return await self._email_labels.add(
            EmailLabel(email_id=email_id, label_id=label_id)
        )

    async def unassign(self, email_id: uuid.UUID, label_id: uuid.UUID) -> bool:
        """Remove a label from an email. Returns ``False`` if not assigned."""
        return await self._email_labels.unassign(email_id, label_id)

    async def list_assignments_for_email(
        self, email_id: uuid.UUID
    ) -> Sequence[EmailLabel]:
        """Return all label assignments for an email."""
        return await self._email_labels.list_by_email(email_id)
