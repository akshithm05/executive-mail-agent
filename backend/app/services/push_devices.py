"""CRUD + validation for a user's registered push devices.

Covers both push channels: "desktop" (``platform="web"``, a browser Web
Push subscription) and "mobile_push" (``platform="ios"``/``"android"``, an
FCM device token). Unlike the singleton channels (see
``app/services/notification_channels.py``), a user may register any number
of devices -- all active ones receive every dispatched push.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

from app.core.crypto import TokenCipher
from app.core.exceptions import ValidationError
from app.infra.models.push_device import PUSH_DEVICE_PLATFORMS, PushDevice
from app.infra.repositories.push_device import PushDeviceRepository

REQUIRED_DEVICE_FIELDS: dict[str, tuple[str, ...]] = {
    "web": ("endpoint", "keys"),
    "ios": ("fcm_token",),
    "android": ("fcm_token",),
}


def validate_device_config(platform: str, config: dict[str, object]) -> None:
    """Raise :class:`ValidationError` if ``config`` is missing a required field."""
    if platform not in PUSH_DEVICE_PLATFORMS:
        raise ValidationError(f"Unknown push platform: {platform!r}")
    missing = [
        field for field in REQUIRED_DEVICE_FIELDS[platform] if not config.get(field)
    ]
    if missing:
        raise ValidationError(
            f"Missing required field(s) for platform {platform!r}: {', '.join(missing)}"
        )


class PushDeviceService:
    """CRUD for a user's registered push (web/mobile) devices."""

    def __init__(self, repository: PushDeviceRepository, cipher: TokenCipher) -> None:
        self._repo = repository
        self._cipher = cipher

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[PushDevice]:
        """Return every device (active or not) for a user."""
        return await self._repo.list_by_user(user_id)

    async def register(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        platform: str,
        config: dict[str, object],
    ) -> PushDevice:
        """Register a new push device."""
        validate_device_config(platform, config)
        ciphertext = self._cipher.encrypt(json.dumps(config))
        return await self._repo.add(
            PushDevice(
                tenant_id=tenant_id,
                user_id=user_id,
                platform=platform,
                token_ciphertext=ciphertext,
                is_active=True,
            )
        )

    async def deactivate(self, user_id: uuid.UUID, device_id: uuid.UUID) -> bool:
        """Deactivate one of a user's devices. Returns False if not found/not theirs."""
        device = await self._repo.get(device_id)
        if device is None or device.user_id != user_id:
            return False
        result = await self._repo.update_fields(device_id, is_active=False)
        return result is not None

    async def delete(self, user_id: uuid.UUID, device_id: uuid.UUID) -> bool:
        """Hard-delete a user's device. Returns False if not found/not theirs."""
        device = await self._repo.get(device_id)
        if device is None or device.user_id != user_id:
            return False
        return await self._repo.delete(device_id)
