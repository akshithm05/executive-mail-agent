"""Preference CRUD service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from app.infra.models.preference import Preference
from app.infra.repositories.preference import PreferenceRepository
from app.services.crud import CRUDService


class PreferenceService(CRUDService[Preference]):
    """CRUD operations for user preferences, plus key-based upsert."""

    def __init__(self, repository: PreferenceRepository) -> None:
        super().__init__(repository)
        self._repo: PreferenceRepository = repository

    async def get_by_key(self, user_id: uuid.UUID, key: str) -> Preference | None:
        """Return a user's preference by key, or ``None`` if unset."""
        return await self._repo.get_by_key(user_id, key)

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[Preference]:
        """Return every active preference for a user."""
        return await self._repo.list_by_user(user_id)

    async def set(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        key: str,
        value: dict[str, Any],
        *,
        category: str | None = None,
    ) -> Preference:
        """Create or update a preference by key (upsert)."""
        existing = await self._repo.get_by_key(user_id, key)
        if existing is not None:
            # existing was just fetched in this transaction, so it is still
            # there for `update` to find; cast rather than assert (no runtime
            # check needed, and asserts can be stripped by `python -O`).
            updated = await self.update(existing.id, value=value, category=category)
            return cast(Preference, updated)
        return await self.create(
            Preference(
                tenant_id=tenant_id,
                user_id=user_id,
                key=key,
                value=value,
                category=category,
            )
        )
