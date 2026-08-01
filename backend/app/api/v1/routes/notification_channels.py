"""Notification-channel configuration endpoints.

Covers the six "singleton" channels a user configures one destination for:
Slack, Discord, Telegram, WhatsApp, email, and webhook. Desktop and mobile
push are multi-device and live under ``/push-devices`` instead (see
``app/api/v1/routes/push_devices.py``).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import (
    ChannelSendersDep,
    CurrentUserDep,
    NotificationChannelConfigServiceDep,
)
from app.core.exceptions import NotFoundError
from app.infra.models.notification_channel_config import SINGLETON_CHANNEL_TYPES
from app.schemas.notification_channel import (
    NotificationChannelConfigRead,
    NotificationChannelConfigUpdate,
)
from app.services.notifications.errors import (
    ChannelDeliveryError,
    ChannelNotConfiguredError,
)

router = APIRouter(prefix="/notification-channels", tags=["notification-channels"])


class ChannelTestResult(BaseModel):
    """Outcome of a test send through one channel."""

    ok: bool
    detail: str | None = None


@router.get(
    "",
    response_model=list[NotificationChannelConfigRead],
    summary="List channel configs",
)
async def list_channel_configs(
    user: CurrentUserDep, service: NotificationChannelConfigServiceDep
) -> list[NotificationChannelConfigRead]:
    """List the current user's configured notification channels."""
    configs = await service.list_by_user(user.id)
    return [NotificationChannelConfigRead.model_validate(c) for c in configs]


@router.put(
    "/{channel_type}",
    response_model=NotificationChannelConfigRead,
    summary="Set a channel config (upsert)",
)
async def set_channel_config(
    channel_type: str,
    body: NotificationChannelConfigUpdate,
    user: CurrentUserDep,
    service: NotificationChannelConfigServiceDep,
) -> NotificationChannelConfigRead:
    """Create or update the current user's config for one channel.

    Raises:
        ValidationError: ``channel_type`` is unknown, or the config is
            missing a field that channel requires (e.g. Slack needs
            ``webhook_url``).
    """
    config = await service.upsert(
        tenant_id=user.tenant_id,
        user_id=user.id,
        channel_type=channel_type,
        config=body.config,
        is_enabled=body.is_enabled,
    )
    return NotificationChannelConfigRead.model_validate(config)


@router.delete(
    "/{channel_type}",
    status_code=204,
    response_model=None,
    summary="Remove a channel config",
)
async def delete_channel_config(
    channel_type: str,
    user: CurrentUserDep,
    service: NotificationChannelConfigServiceDep,
) -> None:
    """Remove the current user's config for one channel."""
    deleted = await service.delete(user.id, channel_type)
    if not deleted:
        raise NotFoundError(f"No {channel_type!r} channel is configured.")


@router.post(
    "/{channel_type}/test",
    response_model=ChannelTestResult,
    summary="Send a test notification through one channel",
)
async def test_channel_config(
    channel_type: str,
    user: CurrentUserDep,
    service: NotificationChannelConfigServiceDep,
    senders: ChannelSendersDep,
) -> ChannelTestResult:
    """Send a one-off test message through the user's configured channel.

    Bypasses rules and quiet hours -- this is a direct connectivity check,
    not a real notification -- and never enqueues a retry on failure.
    """
    if channel_type not in SINGLETON_CHANNEL_TYPES:
        raise NotFoundError(f"Unknown channel type: {channel_type!r}")

    config = await service.get_decrypted_config(user.id, channel_type)
    if config is None:
        raise NotFoundError(f"No {channel_type!r} channel is configured.")

    title = "Test notification"
    body = "This is a test notification from your AI Executive Email Assistant."
    try:
        if channel_type == "slack":
            await senders.slack.send(title=title, body=body, config=config)
        elif channel_type == "discord":
            await senders.discord.send(title=title, body=body, config=config)
        elif channel_type == "telegram":
            await senders.telegram.send(title=title, body=body, config=config)
        elif channel_type == "whatsapp":
            await senders.whatsapp.send(title=title, body=body, config=config)
        elif channel_type == "webhook":
            await senders.webhook.send(
                title=title, body=body, config=config, notification_type="test"
            )
        elif channel_type == "email":
            merged = {**config, "to_address": config.get("to_address") or user.email}
            await senders.email.send(title=title, body=body, config=merged)
    except ChannelNotConfiguredError as exc:
        return ChannelTestResult(ok=False, detail=str(exc))
    except ChannelDeliveryError as exc:
        return ChannelTestResult(ok=False, detail=str(exc))
    return ChannelTestResult(ok=True)
