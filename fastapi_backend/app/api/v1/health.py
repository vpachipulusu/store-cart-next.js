from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.api.auth import require_internal_key
from app.api.deps import HealthServiceDep
from app.core.config import settings
from app.services.provisioning_readiness import check_provisioning_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


class ProvisioningSettingsStatus(BaseModel):
    ready: bool
    missing: list[str]


class ReadyResponse(HealthResponse):
    provisioning: ProvisioningSettingsStatus


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness check. Touches no database or other dependency."""
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    dependencies=[Depends(require_internal_key)],
)
async def readiness_check(
    response: Response, service: HealthServiceDep
) -> ReadyResponse:
    """Readiness check: 200 when the database answers, 503 otherwise.

    Needs the service key (KAN-247): it queries the database, so it must not be an
    open probe on a public URL. Liveness (`/health`) stays open.

    ``provisioning`` names the store provisioning settings that are missing (KAN-248),
    never their values. It is a diagnostic: it does not change the status code.

    Redis is deliberately not checked: rate limiting fails open, so a Redis blip
    must not take the service out of rotation.
    """
    readiness = check_provisioning_settings(settings)
    provisioning = ProvisioningSettingsStatus(
        ready=readiness.ready, missing=list(readiness.missing)
    )
    if await service.is_database_ready():
        return ReadyResponse(status="ok", provisioning=provisioning)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="unavailable", provisioning=provisioning)
