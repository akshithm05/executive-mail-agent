"""Health-check endpoints.

Two distinct probes are exposed, matching container-orchestrator conventions:

* ``/health/live`` — liveness: the process is up and can serve HTTP. It has no
  external dependencies so a failing dependency never triggers a restart loop.
* ``/health/ready`` — readiness: the process can serve *useful* traffic, which
  requires the database to be reachable. Returns 503 when not ready.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from redis.exceptions import RedisError

from app.api.deps import DatabaseDep, RedisClientDep
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
async def ready(
    database: DatabaseDep, redis_client: RedisClientDep, response: Response
) -> ReadinessResponse:
    """Report readiness, checking the database and (informationally) Redis.

    Sets HTTP 503 only when the database is down -- see
    ``ReadinessResponse``'s docstring for why Redis doesn't gate overall
    readiness the same way.
    """
    db_up = await database.ping()
    db_status: CheckStatus = "up" if db_up else "down"

    try:
        redis_up = bool(await redis_client.ping())
    except RedisError:
        redis_up = False
    redis_status: CheckStatus = "up" if redis_up else "down"

    overall: HealthStatus = "ok" if db_up else "degraded"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status=overall, checks={"database": db_status, "redis": redis_status}
    )
