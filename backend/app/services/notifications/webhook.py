"""Generic webhook notification channel.

Posts a JSON payload to a user-supplied URL. If the user also supplied a
shared secret, the request is signed the same way GitHub/Stripe webhooks
are -- an ``X-AEEA-Signature: sha256=<hex>`` header over the raw JSON body,
so the receiver can verify the payload actually came from us.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.services.notifications.errors import ChannelDeliveryError

REQUIRED_CONFIG_FIELDS = ("url",)


class WebhookSender:
    """POSTs a JSON payload to an arbitrary user-configured URL."""

    def __init__(
        self, http_client: httpx.AsyncClient, *, timeout_seconds: float = 10.0
    ) -> None:
        self._http = http_client
        self._timeout = timeout_seconds

    async def send(
        self,
        *,
        title: str,
        body: str,
        config: dict[str, Any],
        notification_type: str = "",
    ) -> None:
        """POST ``{title, body, notification_type}`` to the URL in ``config``.

        Raises:
            ChannelDeliveryError: The URL is missing, or the receiver
                returned a non-2xx response.
        """
        url = config.get("url")
        if not url:
            raise ChannelDeliveryError("Webhook channel config is missing 'url'.")

        payload = {"title": title, "body": body, "notification_type": notification_type}
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        secret = config.get("secret")
        if secret:
            signature = hmac.new(
                secret.encode("utf-8"), raw_body, hashlib.sha256
            ).hexdigest()
            headers["X-AEEA-Signature"] = f"sha256={signature}"

        try:
            response = await self._http.post(
                url, content=raw_body, headers=headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(f"Webhook request failed: {exc}") from exc

        if response.status_code >= 400:
            raise ChannelDeliveryError(
                f"Webhook endpoint returned {response.status_code}: "
                f"{response.text[:500]}"
            )
