"""Exceptions raised by notification channel senders.

These are internal to the notification subsystem -- the dispatch
orchestrator catches them and turns them into a
:class:`~app.infra.models.notification_delivery.NotificationDelivery` audit
row plus (for :class:`ChannelDeliveryError`) a retry-queue entry. They never
propagate to an HTTP response directly, except from the explicit
``POST /notification-channels/{type}/test`` route, which translates them.
"""

from __future__ import annotations


class ChannelNotConfiguredError(Exception):
    """The app-level credentials this channel needs are not configured.

    Raised for provider-level setup (e.g. no Telegram bot token, no SMTP
    host) as opposed to a per-user config problem -- the dispatch
    orchestrator treats this the same as a delivery failure (logs +
    enqueues for retry) rather than crashing, since the operator may
    configure it later.
    """


class ChannelDeliveryError(Exception):
    """A single delivery attempt to a channel failed."""


class DeviceUnregisteredError(ChannelDeliveryError):
    """The push provider reports this device/subscription no longer exists.

    Raised for FCM's ``UNREGISTERED`` error and Web Push's 404/410
    responses -- the dispatch orchestrator deactivates the
    :class:`~app.infra.models.push_device.PushDevice` on this error instead
    of retrying, since retrying a dead endpoint can never succeed.
    """
