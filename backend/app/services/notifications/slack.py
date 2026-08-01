"""Slack notification channel: a user-supplied Incoming Webhook URL.

No app-level credentials needed -- each user creates their own Slack
"Incoming Webhook" (https://api.slack.com/messaging/webhooks) and pastes the
URL in, so this sender needs nothing but ``httpx``.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.notifications.errors import ChannelDeliveryError

REQUIRED_CONFIG_FIELDS = ("webhook_url",)


class SlackSender:
    """Posts a message to a Slack Incoming Webhook."""

    def __init__(
        self, http_client: httpx.AsyncClient, *, timeout_seconds: float = 10.0
    ) -> None:
        self._http = http_client
        self._timeout = timeout_seconds

    async def send(self, *, title: str, body: str, config: dict[str, Any]) -> None:
        """Send ``title``/``body`` to the webhook URL in ``config``.

        Raises:
            ChannelDeliveryError: The webhook URL is missing, or Slack
                returned a non-2xx response.
        """
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise ChannelDeliveryError("Slack channel config is missing 'webhook_url'.")

        text = f"*{title}*\n{body}" if body else f"*{title}*"
        try:
            response = await self._http.post(
                webhook_url, json={"text": text}, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(f"Slack request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ChannelDeliveryError(
                f"Slack webhook returned {response.status_code}: {response.text[:500]}"
            )
