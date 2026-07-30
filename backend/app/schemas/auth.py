"""Auth endpoint response schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class UserProfileResponse(BaseModel):
    """The signed-in user's own profile (``/auth/me``)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    display_name: str
    picture_url: str


class LogoutResponse(BaseModel):
    """Response confirming logout."""

    status: str = Field(default="logged_out")


class TokenRefreshResponse(BaseModel):
    """Response confirming a forced Google access-token refresh."""

    status: str = Field(default="refreshed")
