"""Preference endpoints: the dashboard's Settings page."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, PreferenceServiceDep
from app.schemas.preference import PreferenceRead
from app.schemas.preference import PreferenceUpdate as PreferenceSetRequest

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=list[PreferenceRead], summary="List preferences")
async def list_preferences(
    user: CurrentUserDep, service: PreferenceServiceDep
) -> list[PreferenceRead]:
    """List every preference the current user has set."""
    preferences = await service.list_by_user(user.id)
    return [PreferenceRead.model_validate(p) for p in preferences]


@router.put(
    "/{key}", response_model=PreferenceRead, summary="Set a preference (upsert)"
)
async def set_preference(
    key: str,
    body: PreferenceSetRequest,
    user: CurrentUserDep,
    service: PreferenceServiceDep,
) -> PreferenceRead:
    """Create or update one preference by key (e.g. ``theme``, ``notify_on_urgent``)."""
    preference = await service.set(
        user.tenant_id, user.id, key, body.value or {}, category=body.category
    )
    return PreferenceRead.model_validate(preference)
