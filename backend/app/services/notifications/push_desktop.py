"""Desktop notification channel: browser Web Push (RFC 8030), VAPID-signed.

``pywebpush`` performs the actual encrypted POST synchronously (it's built
on ``requests``, not an async HTTP client), so the call is offloaded to a
worker thread via ``asyncio.to_thread`` to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pywebpush import WebPushException, webpush

from app.config.settings import PushSettings
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
    DeviceUnregisteredError,
)

# A registered browser `PushSubscription`, JSON-serialized -- see
# `app/api/v1/routes/push_devices.py` for the registration payload shape.
REQUIRED_DEVICE_FIELDS = ("endpoint", "keys")

_UNREGISTERED_STATUS_CODES = (404, 410)


class DesktopPushSender:
    """Sends one Web Push notification to one registered browser subscription."""

    def __init__(self, settings: PushSettings) -> None:
        self._settings = settings

    async def send(
        self, *, title: str, body: str, device_config: dict[str, Any]
    ) -> None:
        """Push ``title``/``body`` to the subscription in ``device_config``.

        Raises:
            ChannelNotConfiguredError: No VAPID key pair is configured.
            DeviceUnregisteredError: The browser has unsubscribed or the
                subscription has expired -- the caller should deactivate
                this device rather than retry.
            ChannelDeliveryError: Any other delivery failure.
        """
        if not self._settings.is_desktop_configured:
            raise ChannelNotConfiguredError(
                "Desktop push (VAPID keys) is not configured."
            )

        subscription_info = {
            "endpoint": device_config["endpoint"],
            "keys": device_config["keys"],
        }
        payload = json.dumps({"title": title, "body": body})

        await asyncio.to_thread(self._send_sync, subscription_info, payload)

    def _send_sync(self, subscription_info: dict[str, Any], payload: str) -> None:
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=self._settings.vapid_private_key,
                vapid_claims={"sub": self._settings.vapid_subject},
                timeout=self._settings.request_timeout_seconds,
            )
        except WebPushException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in _UNREGISTERED_STATUS_CODES:
                raise DeviceUnregisteredError(
                    f"Push subscription is no longer valid ({status_code})."
                ) from exc
            raise ChannelDeliveryError(f"Web Push send failed: {exc}") from exc
