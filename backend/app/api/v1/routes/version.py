"""Version endpoint.

Exposes the running build's identity (name, semantic version, environment, and
git commit) so operators and the frontend can confirm exactly what is deployed.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.deps import SettingsDep
from app.schemas.system import VersionResponse

router = APIRouter(tags=["system"])


@router.get("/version", response_model=VersionResponse, summary="Build version")
async def version(settings: SettingsDep) -> VersionResponse:
    """Return metadata describing the running application build."""
    return VersionResponse(
        name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        git_sha=settings.git_sha,
    )
