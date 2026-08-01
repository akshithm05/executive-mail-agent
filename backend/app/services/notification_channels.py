"""CRUD + validation for a user's singleton notification-channel configs.

"Singleton" channels are Slack/Discord/Telegram/WhatsApp/email/webhook --
exactly one destination per user (see the module docstring on
``app/infra/models/notification_channel_config.py``). Desktop and
mobile_push are multi-device and handled by
``app/services/push_devices.py`` instead.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import cast

from app.core.crypto import TokenCipher
from app.core.exceptions import ValidationError
from app.infra.models.notification_channel_config import (
    SINGLETON_CHANNEL_TYPES,
    NotificationChannelConfig,
)
from app.infra.repositories.notification_channel_config import (
    NotificationChannelConfigRepository,
)

# The config fields each channel type requires -- mirrors each sender's
# `REQUIRED_CONFIG_FIELDS` constant (see `app/services/notifications/`) but
# duplicated here as plain data so this module doesn't need to import every
# sender class just to validate a config shape.
REQUIRED_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "slack": ("webhook_url",),
    "discord": ("webhook_url",),
    "telegram": ("chat_id",),
    "whatsapp": ("to_number",),
    "email": (),  # to_address is optional -- defaults to the user's account email
    "webhook": ("url",),
}


def validate_channel_config(channel_type: str, config: dict[str, object]) -> None:
    """Raise :class:`ValidationError` if ``config`` is missing a required field."""
    if channel_type not in SINGLETON_CHANNEL_TYPES:
        raise ValidationError(f"Unknown channel type: {channel_type!r}")
    missing = [
        field for field in REQUIRED_CONFIG_FIELDS[channel_type] if not config.get(field)
    ]
    if missing:
        raise ValidationError(
            f"Missing required field(s) for {channel_type!r}: {', '.join(missing)}"
        )


class NotificationChannelConfigService:
    """CRUD for a user's singleton notification-channel configurations."""

    def __init__(
        self, repository: NotificationChannelConfigRepository, cipher: TokenCipher
    ) -> None:
        self._repo = repository
        self._cipher = cipher

    async def list_by_user(
        self, user_id: uuid.UUID
    ) -> Sequence[NotificationChannelConfig]:
        """Return every channel config for a user (enabled or not)."""
        return await self._repo.list_by_user(user_id)

    async def get_decrypted_config(
        self, user_id: uuid.UUID, channel_type: str
    ) -> dict[str, object] | None:
        """Return a user's decrypted config for one channel, or ``None`` if unset."""
        row = await self._repo.get_by_user_and_channel(user_id, channel_type)
        if row is None:
            return None
        decrypted: dict[str, object] = json.loads(
            self._cipher.decrypt(row.config_ciphertext)
        )
        return decrypted

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        channel_type: str,
        config: dict[str, object],
        is_enabled: bool = True,
    ) -> NotificationChannelConfig:
        """Create or update (upsert) a user's config for one channel."""
        validate_channel_config(channel_type, config)
        ciphertext = self._cipher.encrypt(json.dumps(config))
        existing = await self._repo.get_by_user_and_channel(user_id, channel_type)
        if existing is not None:
            updated = await self._repo.update_fields(
                existing.id, config_ciphertext=ciphertext, is_enabled=is_enabled
            )
            return cast(NotificationChannelConfig, updated)
        return await self._repo.add(
            NotificationChannelConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_type=channel_type,
                config_ciphertext=ciphertext,
                is_enabled=is_enabled,
            )
        )

    async def delete(self, user_id: uuid.UUID, channel_type: str) -> bool:
        """Delete a user's config for one channel. Returns False if it did not exist."""
        existing = await self._repo.get_by_user_and_channel(user_id, channel_type)
        if existing is None:
            return False
        return await self._repo.delete(existing.id)
