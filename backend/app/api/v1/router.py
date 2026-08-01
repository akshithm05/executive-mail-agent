"""API v1 aggregate router.

Collects every v1 route module under a single router that ``main`` mounts at
the configured API prefix. New route modules are wired in here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    analytics,
    auth,
    calendar_events,
    dashboard,
    draft_replies,
    emails,
    gmail,
    health,
    notification_channels,
    notification_rules,
    notifications,
    preferences,
    push_devices,
    quiet_hours,
    system,
    tasks,
    version,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(version.router)
api_router.include_router(auth.router)
api_router.include_router(gmail.router)
api_router.include_router(draft_replies.router)
api_router.include_router(emails.router)
api_router.include_router(tasks.router)
api_router.include_router(calendar_events.router)
api_router.include_router(notifications.router)
api_router.include_router(notification_channels.router)
api_router.include_router(notification_rules.router)
api_router.include_router(quiet_hours.router)
api_router.include_router(push_devices.router)
api_router.include_router(preferences.router)
api_router.include_router(dashboard.router)
api_router.include_router(analytics.router)
api_router.include_router(system.router)

__all__ = ["api_router"]
