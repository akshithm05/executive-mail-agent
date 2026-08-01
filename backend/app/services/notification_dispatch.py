"""Multi-channel notification dispatch orchestrator.

The single entry point every notification-creating call site (reminder
dispatch, the email-triage graph's ``notification`` node, digest
generation) should call right after persisting a
:class:`~app.infra.models.notification.Notification` row. It owns the full
pipeline for that row:

1. **Rules** -- does this notification pass the user's custom filters (see
   ``app/services/notification_rules.py``)? If not, log ``skipped_rule``
   and stop; the in-app row still exists, only external fan-out is skipped.
2. **Quiet hours** -- is delivery inside the user's configured quiet-hours
   window (see ``app/services/quiet_hours.py``)? If so (and the
   notification isn't urgent, or overrides are off), every channel is
   *deferred*: logged, and re-enqueued on the retry queue with
   ``next_attempt_at`` set to the moment quiet hours end.
3. **Fan-out** -- for every enabled singleton channel config (Slack,
   Discord, Telegram, WhatsApp, email, webhook) and every active push
   device (desktop web-push, mobile FCM), attempt delivery. Each channel
   is isolated in its own try/except -- one bad Slack webhook never blocks
   the user's other channels. A failure is logged and enqueued on the
   retry queue (see ``app/scheduler.py``'s ``process_retry_queue`` job,
   ``job_type="notification_delivery"``); an unregistered push device is
   deactivated instead of retried, since retrying a dead endpoint can
   never succeed.

Dispatch is always best-effort: a failure anywhere in this pipeline is
caught by the caller (never propagated), because the in-app notification
row is the source of truth and must exist regardless of whether any
external channel could be reached.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging import get_logger
from app.config.settings import Settings
from app.core.crypto import TokenCipher
from app.core.time import utcnow
from app.infra.models.notification import Notification
from app.infra.models.notification_channel_config import NotificationChannelConfig
from app.infra.models.notification_delivery import NotificationDelivery
from app.infra.models.push_device import PushDevice
from app.infra.repositories.failed_job import FailedJobRepository
from app.infra.repositories.notification import NotificationRepository
from app.infra.repositories.notification_channel_config import (
    NotificationChannelConfigRepository,
)
from app.infra.repositories.notification_delivery import NotificationDeliveryRepository
from app.infra.repositories.notification_quiet_hours import (
    NotificationQuietHoursRepository,
)
from app.infra.repositories.notification_rule import NotificationRuleRepository
from app.infra.repositories.push_device import PushDeviceRepository
from app.infra.repositories.user import UserRepository
from app.services.notification_rules import should_deliver
from app.services.notifications.discord import DiscordSender
from app.services.notifications.errors import (
    ChannelDeliveryError,
    DeviceUnregisteredError,
)
from app.services.notifications.push_desktop import DesktopPushSender
from app.services.notifications.push_mobile import MobilePushSender
from app.services.notifications.slack import SlackSender
from app.services.notifications.smtp_email import SMTPEmailSender
from app.services.notifications.telegram import TelegramSender
from app.services.notifications.webhook import WebhookSender
from app.services.notifications.whatsapp import WhatsAppSender
from app.services.quiet_hours import (
    is_urgent,
    is_within_quiet_hours,
    next_quiet_hours_end,
)
from app.services.retry_queue import RetryQueueService

logger = get_logger(__name__)

_PUSH_PLATFORMS_BY_CHANNEL = {"desktop": ("web",), "mobile_push": ("ios", "android")}


@dataclass
class ChannelSenders:
    """One sender instance per external notification channel."""

    slack: SlackSender
    discord: DiscordSender
    telegram: TelegramSender
    whatsapp: WhatsAppSender
    webhook: WebhookSender
    email: SMTPEmailSender
    desktop_push: DesktopPushSender
    mobile_push: MobilePushSender


class NotificationDispatchService:
    """Fans an in-app notification out to every channel the user has configured."""

    def __init__(
        self,
        *,
        notification_repo: NotificationRepository,
        channel_config_repo: NotificationChannelConfigRepository,
        push_device_repo: PushDeviceRepository,
        rule_repo: NotificationRuleRepository,
        quiet_hours_repo: NotificationQuietHoursRepository,
        delivery_repo: NotificationDeliveryRepository,
        user_repo: UserRepository,
        retry_queue: RetryQueueService,
        cipher: TokenCipher,
        senders: ChannelSenders,
        max_attempts: int = 5,
    ) -> None:
        self._notifications = notification_repo
        self._channel_configs = channel_config_repo
        self._push_devices = push_device_repo
        self._rules = rule_repo
        self._quiet_hours = quiet_hours_repo
        self._deliveries = delivery_repo
        self._users = user_repo
        self._retry_queue = retry_queue
        self._cipher = cipher
        self._senders = senders
        self._max_attempts = max_attempts

    async def dispatch(self, notification: Notification) -> None:
        """Fan ``notification`` (already persisted) out to every enabled channel."""
        rules = await self._rules.list_enabled_by_user(notification.user_id)
        if not should_deliver(rules, notification):
            await self._log(notification, channel_type="*", status="skipped_rule")
            return

        user = await self._users.get(notification.user_id)
        if user is None:
            return

        quiet_hours = await self._quiet_hours.get_by_user(notification.user_id)
        deferred_until: datetime | None = None
        if quiet_hours is not None and is_within_quiet_hours(quiet_hours):
            urgent_bypass = quiet_hours.allow_urgent_override and is_urgent(
                notification.type
            )
            if not urgent_bypass:
                deferred_until = next_quiet_hours_end(quiet_hours)

        for config_row in await self._channel_configs.list_enabled_by_user(
            notification.user_id
        ):
            await self._dispatch_singleton(
                notification, user.email, config_row, deferred_until
            )

        for channel_type, platforms in _PUSH_PLATFORMS_BY_CHANNEL.items():
            devices = await self._push_devices.list_active_by_user_and_platforms(
                notification.user_id, platforms
            )
            for device in devices:
                await self._dispatch_push(
                    notification, channel_type, device, deferred_until
                )

    async def retry_one(
        self,
        *,
        notification_id: uuid.UUID,
        channel_type: str,
        target: str,
        device_id: uuid.UUID | None = None,
    ) -> None:
        """Retry exactly one previously-failed or deferred channel delivery.

        Called by the scheduled retry-queue processor
        (``app/scheduler.py``'s ``_retry_notification_delivery``) for
        ``job_type="notification_delivery"`` entries. Re-raises on failure
        so the caller's retry/dead-letter bookkeeping applies; returns
        normally on success *or* on a now-defunct target (deleted
        notification, disabled channel, deactivated device) since there is
        nothing left to retry.
        """
        notification = await self._notifications.get(notification_id)
        if notification is None:
            return

        if target == "push":
            await self._retry_push(notification, channel_type, device_id)
            return

        config_row = await self._channel_configs.get_by_user_and_channel(
            notification.user_id, channel_type
        )
        if config_row is None or not config_row.is_enabled:
            return
        user = await self._users.get(notification.user_id)
        if user is None:
            return

        try:
            config = self._decrypt_config(config_row.config_ciphertext)
            await self._send_singleton(channel_type, notification, user.email, config)
        except Exception as exc:
            await self._log(
                notification, channel_type=channel_type, status="failed", error=str(exc)
            )
            raise
        await self._log(
            notification, channel_type=channel_type, status="sent", sent_at=utcnow()
        )

    async def _retry_push(
        self, notification: Notification, channel_type: str, device_id: uuid.UUID | None
    ) -> None:
        if device_id is None:
            return
        device = await self._push_devices.get(device_id)
        if device is None or not device.is_active:
            return

        try:
            device_config = self._decrypt_config(device.token_ciphertext)
            sender = (
                self._senders.desktop_push
                if channel_type == "desktop"
                else self._senders.mobile_push
            )
            await sender.send(
                title=notification.title,
                body=notification.body,
                device_config=device_config,
            )
        except DeviceUnregisteredError as exc:
            await self._push_devices.update_fields(device.id, is_active=False)
            await self._log(
                notification, channel_type=channel_type, status="failed", error=str(exc)
            )
            return
        except Exception as exc:
            await self._log(
                notification, channel_type=channel_type, status="failed", error=str(exc)
            )
            raise
        await self._push_devices.update_fields(device.id, last_used_at=utcnow())
        await self._log(
            notification, channel_type=channel_type, status="sent", sent_at=utcnow()
        )

    async def _dispatch_singleton(
        self,
        notification: Notification,
        user_email: str,
        config_row: NotificationChannelConfig,
        deferred_until: datetime | None,
    ) -> None:
        channel_type = config_row.channel_type
        if deferred_until is not None:
            await self._defer(
                notification, channel_type, target="singleton", until=deferred_until
            )
            return

        try:
            config = self._decrypt_config(config_row.config_ciphertext)
            await self._send_singleton(channel_type, notification, user_email, config)
        except Exception as exc:
            await self._log(
                notification, channel_type=channel_type, status="failed", error=str(exc)
            )
            await self._retry_queue.enqueue_failure(
                tenant_id=notification.tenant_id,
                user_id=notification.user_id,
                job_type="notification_delivery",
                payload={
                    "notification_id": str(notification.id),
                    "channel_type": channel_type,
                    "target": "singleton",
                },
                error=exc,
                max_attempts=self._max_attempts,
            )
        else:
            await self._log(
                notification, channel_type=channel_type, status="sent", sent_at=utcnow()
            )

    async def _dispatch_push(
        self,
        notification: Notification,
        channel_type: str,
        device: PushDevice,
        deferred_until: datetime | None,
    ) -> None:
        if deferred_until is not None:
            await self._defer(
                notification,
                channel_type,
                target="push",
                until=deferred_until,
                device_id=device.id,
            )
            return

        try:
            device_config = self._decrypt_config(device.token_ciphertext)
            sender = (
                self._senders.desktop_push
                if channel_type == "desktop"
                else self._senders.mobile_push
            )
            await sender.send(
                title=notification.title,
                body=notification.body,
                device_config=device_config,
            )
        except DeviceUnregisteredError as exc:
            await self._push_devices.update_fields(device.id, is_active=False)
            await self._log(
                notification, channel_type=channel_type, status="failed", error=str(exc)
            )
        except Exception as exc:
            await self._log(
                notification, channel_type=channel_type, status="failed", error=str(exc)
            )
            await self._retry_queue.enqueue_failure(
                tenant_id=notification.tenant_id,
                user_id=notification.user_id,
                job_type="notification_delivery",
                payload={
                    "notification_id": str(notification.id),
                    "channel_type": channel_type,
                    "target": "push",
                    "device_id": str(device.id),
                },
                error=exc,
                max_attempts=self._max_attempts,
            )
        else:
            await self._push_devices.update_fields(device.id, last_used_at=utcnow())
            await self._log(
                notification, channel_type=channel_type, status="sent", sent_at=utcnow()
            )

    async def _defer(
        self,
        notification: Notification,
        channel_type: str,
        *,
        target: str,
        until: datetime,
        device_id: uuid.UUID | None = None,
    ) -> None:
        await self._log(notification, channel_type=channel_type, status="deferred")
        payload: dict[str, Any] = {
            "notification_id": str(notification.id),
            "channel_type": channel_type,
            "target": target,
        }
        if device_id is not None:
            payload["device_id"] = str(device_id)
        await self._retry_queue.enqueue_failure(
            tenant_id=notification.tenant_id,
            user_id=notification.user_id,
            job_type="notification_delivery",
            payload=payload,
            error="deferred: quiet hours",
            max_attempts=self._max_attempts,
            next_attempt_at=until,
        )

    async def _send_singleton(
        self,
        channel_type: str,
        notification: Notification,
        user_email: str,
        config: dict[str, Any],
    ) -> None:
        title, body = notification.title, notification.body
        if channel_type == "slack":
            await self._senders.slack.send(title=title, body=body, config=config)
        elif channel_type == "discord":
            await self._senders.discord.send(title=title, body=body, config=config)
        elif channel_type == "telegram":
            await self._senders.telegram.send(title=title, body=body, config=config)
        elif channel_type == "whatsapp":
            await self._senders.whatsapp.send(title=title, body=body, config=config)
        elif channel_type == "webhook":
            await self._senders.webhook.send(
                title=title,
                body=body,
                config=config,
                notification_type=notification.type,
            )
        elif channel_type == "email":
            merged = {**config, "to_address": config.get("to_address") or user_email}
            await self._senders.email.send(title=title, body=body, config=merged)
        else:
            raise ChannelDeliveryError(
                f"unknown singleton channel_type: {channel_type!r}"
            )

    def _decrypt_config(self, ciphertext: str) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self._cipher.decrypt(ciphertext))
        return payload

    async def _log(
        self,
        notification: Notification,
        *,
        channel_type: str,
        status: str,
        error: str | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        await self._deliveries.add(
            NotificationDelivery(
                tenant_id=notification.tenant_id,
                notification_id=notification.id,
                channel_type=channel_type,
                status=status,
                error_message=(error[:2000] if error else None),
                sent_at=sent_at,
            )
        )


def build_channel_senders(
    http_client: httpx.AsyncClient, settings: Settings
) -> ChannelSenders:
    """Build one sender instance per channel, sharing the given HTTP client.

    Shared factory so every construction site (the scheduler, the
    email-triage graph, and the API's DI layer) builds senders from the
    exact same settings-derived configuration.
    """
    return ChannelSenders(
        slack=SlackSender(
            http_client,
            timeout_seconds=settings.notification.webhook_request_timeout_seconds,
        ),
        discord=DiscordSender(
            http_client,
            timeout_seconds=settings.notification.webhook_request_timeout_seconds,
        ),
        telegram=TelegramSender(http_client, settings.telegram),
        whatsapp=WhatsAppSender(http_client, settings.whatsapp),
        webhook=WebhookSender(
            http_client,
            timeout_seconds=settings.notification.webhook_request_timeout_seconds,
        ),
        email=SMTPEmailSender(settings.smtp),
        desktop_push=DesktopPushSender(settings.push),
        mobile_push=MobilePushSender(http_client, settings.push),
    )


def build_notification_dispatch_service(
    session: AsyncSession, settings: Settings, http_client: httpx.AsyncClient
) -> NotificationDispatchService:
    """Build a fully-wired :class:`NotificationDispatchService` for one session.

    Shared factory used by every call site that dispatches a notification
    (``app/scheduler.py``, ``app/agents/email_agent.py``, and the API's DI
    layer in ``app/api/deps.py``) so the wiring lives in exactly one place.
    """
    return NotificationDispatchService(
        notification_repo=NotificationRepository(session),
        channel_config_repo=NotificationChannelConfigRepository(session),
        push_device_repo=PushDeviceRepository(session),
        rule_repo=NotificationRuleRepository(session),
        quiet_hours_repo=NotificationQuietHoursRepository(session),
        delivery_repo=NotificationDeliveryRepository(session),
        user_repo=UserRepository(session),
        retry_queue=RetryQueueService(FailedJobRepository(session)),
        cipher=TokenCipher(settings.security.token_encryption_key),
        senders=build_channel_senders(http_client, settings),
        max_attempts=settings.notification.delivery_max_attempts,
    )
