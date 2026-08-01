"""Telegram notification channel: the app's own bot, one chat per user.

One Telegram bot belongs to this application (``TELEGRAM_BOT_TOKEN``); each
user starts a chat with it and gives us the resulting numeric ``chat_id``
(stored, encrypted, in their :class:`~app.infra.models.
notification_channel_config.NotificationChannelConfig`).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import TelegramSettings
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
)

REQUIRED_CONFIG_FIELDS = ("chat_id",)


class TelegramSender:
    """Sends a message via the Telegram Bot API's ``sendMessage`` method."""

    def __init__(
        self, http_client: httpx.AsyncClient, settings: TelegramSettings
    ) -> None:
        self._http = http_client
        self._settings = settings

    async def send(self, *, title: str, body: str, config: dict[str, Any]) -> None:
        """Send ``title``/``body`` to the chat id in ``config``.

        Raises:
            ChannelNotConfiguredError: No app-level bot token is configured.
            ChannelDeliveryError: The chat id is missing, or Telegram
                returned a non-2xx / non-``ok`` response.
        """
        if not self._settings.is_configured:
            raise ChannelNotConfiguredError("Telegram bot token is not configured.")

        chat_id = config.get("chat_id")
        if not chat_id:
            raise ChannelDeliveryError("Telegram channel config is missing 'chat_id'.")

        text = f"*{title}*\n{body}" if body else f"*{title}*"
        url = f"{self._settings.api_base_url}/bot{self._settings.bot_token}/sendMessage"
        try:
            response = await self._http.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=self._settings.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(f"Telegram request failed: {exc}") from exc

        ok = False
        if response.status_code < 400:
            try:
                ok = bool(response.json().get("ok", False))
            except ValueError:
                ok = False
        if not ok:
            raise ChannelDeliveryError(
                f"Telegram sendMessage returned {response.status_code}: "
                f"{response.text[:500]}"
            )
