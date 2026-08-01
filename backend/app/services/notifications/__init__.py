"""Multi-channel notification delivery: one sender module per channel.

Each sender is a small, stateless class wrapping one outbound integration
(Slack/Discord/Telegram/WhatsApp/SMTP/webhook/Web-Push/FCM). They are
intentionally *not* responsible for retrying, rule evaluation, quiet hours,
or persistence -- see :class:`~app.services.notification_dispatch.
NotificationDispatchService` for the orchestrator that owns all of that.
"""
