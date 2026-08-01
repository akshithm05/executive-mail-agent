"""WhatsApp notification channel, via Twilio's WhatsApp Business API.

Twilio's messaging API is plain REST over HTTP Basic Auth, so no SDK is
needed -- just ``httpx``. The Twilio account (and its approved WhatsApp
sender number) belongs to this application; each user supplies only their
own destination WhatsApp number.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import WhatsAppSettings
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
)

REQUIRED_CONFIG_FIELDS = ("to_number",)

_WHATSAPP_PREFIX = "whatsapp:"


def _as_whatsapp_address(number: str) -> str:
    number = number.strip()
    return (
        number if number.startswith(_WHATSAPP_PREFIX) else f"{_WHATSAPP_PREFIX}{number}"
    )


class WhatsAppSender:
    """Sends a WhatsApp message via the Twilio Messages API."""

    def __init__(
        self, http_client: httpx.AsyncClient, settings: WhatsAppSettings
    ) -> None:
        self._http = http_client
        self._settings = settings

    async def send(self, *, title: str, body: str, config: dict[str, Any]) -> None:
        """Send ``title``/``body`` to the WhatsApp number in ``config``.

        Raises:
            ChannelNotConfiguredError: No app-level Twilio credentials are
                configured.
            ChannelDeliveryError: The destination number is missing, or
                Twilio returned a non-2xx response.
        """
        if not self._settings.is_configured:
            raise ChannelNotConfiguredError(
                "Twilio WhatsApp credentials are not configured."
            )

        to_number = config.get("to_number")
        if not to_number:
            raise ChannelDeliveryError(
                "WhatsApp channel config is missing 'to_number'."
            )

        text = f"*{title}*\n{body}" if body else f"*{title}*"
        url = (
            f"{self._settings.api_base_url}/2010-04-01/Accounts/"
            f"{self._settings.twilio_account_sid}/Messages.json"
        )
        try:
            response = await self._http.post(
                url,
                auth=(
                    self._settings.twilio_account_sid,
                    self._settings.twilio_auth_token,
                ),
                data={
                    "From": _as_whatsapp_address(self._settings.from_number),
                    "To": _as_whatsapp_address(to_number),
                    "Body": text,
                },
                timeout=self._settings.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(
                f"Twilio WhatsApp request failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise ChannelDeliveryError(
                f"Twilio WhatsApp send returned {response.status_code}: "
                f"{response.text[:500]}"
            )
