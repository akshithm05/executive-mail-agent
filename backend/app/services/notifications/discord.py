"""Discord notification channel: a user-supplied Webhook URL.

Same shape as Slack -- a per-user Discord channel webhook
(https://support.discord.com/hc/en-us/articles/228383668), no app-level
credentials needed.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.notifications.errors import ChannelDeliveryError

REQUIRED_CONFIG_FIELDS = ("webhook_url",)

# Discord's hard cap on a message's `content` field.
_MAX_CONTENT_LENGTH = 2000


class DiscordSender:
    """Posts a message to a Discord channel webhook."""

    def __init__(
        self, http_client: httpx.AsyncClient, *, timeout_seconds: float = 10.0
    ) -> None:
        self._http = http_client
        self._timeout = timeout_seconds

    async def send(self, *, title: str, body: str, config: dict[str, Any]) -> None:
        """Send ``title``/``body`` to the webhook URL in ``config``.

        Raises:
            ChannelDeliveryError: The webhook URL is missing, or Discord
                returned a non-2xx response.
        """
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise ChannelDeliveryError(
                "Discord channel config is missing 'webhook_url'."
            )

        content = f"**{title}**\n{body}" if body else f"**{title}**"
        content = content[:_MAX_CONTENT_LENGTH]
        try:
            response = await self._http.post(
                webhook_url, json={"content": content}, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(f"Discord request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ChannelDeliveryError(
                f"Discord webhook returned {response.status_code}: "
                f"{response.text[:500]}"
            )
