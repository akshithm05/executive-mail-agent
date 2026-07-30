"""API v1 aggregate router.

Collects every v1 route module under a single router that ``main`` mounts at
the configured API prefix. New route modules are wired in here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import auth, draft_replies, gmail, health, version

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(version.router)
api_router.include_router(auth.router)
api_router.include_router(gmail.router)
api_router.include_router(draft_replies.router)

__all__ = ["api_router"]
