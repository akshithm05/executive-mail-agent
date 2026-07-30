"""System endpoint response schemas.

These Pydantic models define the public contract for the operational endpoints
(``/health/*`` and ``/version``). Keeping them here means the FastAPI
OpenAPI schema — and therefore the generated frontend types — stay accurate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

HealthStatus = Literal["ok", "degraded"]
CheckStatus = Literal["up", "down"]


class LivenessResponse(BaseModel):
    """Response for the liveness probe."""

    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    """Response for the readiness probe.

    ``status`` is ``ok`` only when every dependency check is ``up``.
    """

    status: HealthStatus = Field(description="Overall readiness status.")
    checks: dict[str, CheckStatus] = Field(
        description="Per-dependency health, keyed by dependency name."
    )


class VersionResponse(BaseModel):
    """Response describing the running build."""

    name: str = Field(description="Human-readable application name.")
    version: str = Field(description="Semantic version of the application.")
    environment: str = Field(description="Deployment environment.")
    git_sha: str = Field(description="Git commit the build was produced from.")


class ProblemDetail(BaseModel):
    """RFC 9457 problem details response body."""

    type: str = Field(default="about:blank", description="Error type URI.")
    title: str = Field(description="Short, human-readable summary.")
    status: int = Field(description="HTTP status code.")
    code: str = Field(description="Stable machine-readable error code.")
    detail: str = Field(description="Human-readable explanation.")
    request_id: str | None = Field(
        default=None, description="Correlation id for this request."
    )
    errors: dict[str, object] | None = Field(
        default=None, description="Optional structured error context."
    )
