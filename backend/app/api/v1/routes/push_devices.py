"""Push-device registration endpoints (desktop web-push + mobile FCM)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, PushDeviceServiceDep
from app.core.exceptions import NotFoundError
from app.schemas.push_device import PushDeviceRead, PushDeviceRegister

router = APIRouter(prefix="/push-devices", tags=["push-devices"])


@router.get(
    "", response_model=list[PushDeviceRead], summary="List registered push devices"
)
async def list_push_devices(
    user: CurrentUserDep, service: PushDeviceServiceDep
) -> list[PushDeviceRead]:
    """List every push device (active or not) the current user has registered."""
    devices = await service.list_by_user(user.id)
    return [PushDeviceRead.model_validate(d) for d in devices]


@router.post("", response_model=PushDeviceRead, summary="Register a push device")
async def register_push_device(
    body: PushDeviceRegister, user: CurrentUserDep, service: PushDeviceServiceDep
) -> PushDeviceRead:
    """Register a new push device.

    ``platform="web"`` registers a browser Web Push subscription (desktop
    notifications); ``platform="ios"``/``"android"`` registers an FCM device
    token (mobile push).

    Raises:
        ValidationError: ``platform`` is unknown, or ``config`` is missing a
            field that platform requires.
    """
    device = await service.register(
        tenant_id=user.tenant_id,
        user_id=user.id,
        platform=body.platform,
        config=body.config,
    )
    return PushDeviceRead.model_validate(device)


@router.delete(
    "/{device_id}", status_code=204, response_model=None, summary="Remove a push device"
)
async def delete_push_device(
    device_id: uuid.UUID, user: CurrentUserDep, service: PushDeviceServiceDep
) -> None:
    """Remove one of the current user's push devices."""
    deleted = await service.delete(user.id, device_id)
    if not deleted:
        raise NotFoundError("No push device with this id was found.")
