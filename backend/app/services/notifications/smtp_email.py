"""Email notification channel, via outbound SMTP.

Distinct from Gmail (used to *read* the user's inbox) -- this is the
assistant sending its own notification emails, to an address the user
configures (the dispatch orchestrator defaults it to their account email
when no override is set).
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import aiosmtplib

from app.config.settings import SMTPSettings
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
)

REQUIRED_CONFIG_FIELDS = ("to_address",)


class SMTPEmailSender:
    """Sends a notification email over SMTP."""

    def __init__(self, settings: SMTPSettings) -> None:
        self._settings = settings

    async def send(self, *, title: str, body: str, config: dict[str, Any]) -> None:
        """Send ``title``/``body`` to the address in ``config``.

        Raises:
            ChannelNotConfiguredError: No app-level SMTP host is configured.
            ChannelDeliveryError: The destination address is missing, or
                the SMTP server rejected/errored on the send.
        """
        if not self._settings.is_configured:
            raise ChannelNotConfiguredError("SMTP is not configured.")

        to_address = config.get("to_address")
        if not to_address:
            raise ChannelDeliveryError("Email channel config is missing 'to_address'.")

        message = EmailMessage()
        message["From"] = self._settings.from_address
        message["To"] = to_address
        message["Subject"] = title
        message.set_content(body)

        try:
            await aiosmtplib.send(
                message,
                hostname=self._settings.host,
                port=self._settings.port,
                username=self._settings.username or None,
                password=self._settings.password or None,
                start_tls=self._settings.use_tls,
                timeout=self._settings.request_timeout_seconds,
            )
        except aiosmtplib.SMTPException as exc:
            raise ChannelDeliveryError(f"SMTP send failed: {exc}") from exc
        except OSError as exc:
            raise ChannelDeliveryError(f"SMTP connection failed: {exc}") from exc
