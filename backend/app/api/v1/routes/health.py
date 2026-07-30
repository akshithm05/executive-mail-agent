"""Health-check endpoints.

Two distinct probes are exposed, matching container-orchestrator conventions:

* ``/health/live`` — liveness: the process is up and can serve HTTP. It has no
  external dependencies so a failing dependency never triggers a restart loop.
* ``/health/ready`` — readiness: the process can serve *useful* traffic, which
  requires the database to be reachable. Returns 503 when not ready.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import DatabaseDep
from app.schemas.system import (
    CheckStatus,
    HealthStatus,
    LivenessResponse,
    ReadinessResponse,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
async def live() -> LivenessResponse:
    """Return ``ok`` as long as the process can handle requests."""
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(database: DatabaseDep, response: Response) -> ReadinessResponse:
    """Report readiness, checking that the database answers a query.

    Sets HTTP 503 when any dependency is down so orchestrators withhold
    traffic until the instance recovers.
    """
    db_up = await database.ping()
    db_status: CheckStatus = "up" if db_up else "down"
    overall: HealthStatus = "ok" if db_up else "degraded"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status=overall, checks={"database": db_status})
