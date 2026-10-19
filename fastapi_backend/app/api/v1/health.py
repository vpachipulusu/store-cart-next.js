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


class MigrationsStatus(BaseModel):
    pending: bool
    current: str | None
    head: str


class ReadyResponse(HealthResponse):
    provisioning: ProvisioningSettingsStatus
    migrations: MigrationsStatus | None = None


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
    """Readiness check: 200 when the database answers and is migrated, 503 otherwise.

    Needs the service key (KAN-247): it queries the database, so it must not be an
    open probe on a public URL. Liveness (`/health`) stays open.

    ``provisioning`` names the store provisioning settings that are missing (KAN-248),
    never their values. It is a diagnostic: it does not change the status code.

    ``migrations`` compares the platform database's Alembic revision with this build's
    head (KAN-253). Behind (or unreadable) answers 503 with status
    ``migrations_pending``: no deploy runs ``alembic upgrade head`` (ADR-011), and code
    on an unmigrated schema fails every query on the changed tables. Store databases
    are not checked here.

    Redis is deliberately not checked: rate limiting fails open, so a Redis blip
    must not take the service out of rotation.
    """
    readiness = check_provisioning_settings(settings)
    provisioning = ProvisioningSettingsStatus(
        ready=readiness.ready, missing=list(readiness.missing)
    )
    if not await service.is_database_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="unavailable", provisioning=provisioning)
    schema = await service.schema_status()
    if schema is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="unavailable", provisioning=provisioning)
    migrations = MigrationsStatus(
        pending=schema.pending, current=schema.current, head=schema.head
    )
    if schema.pending:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            status="migrations_pending",
            provisioning=provisioning,
            migrations=migrations,
        )
    return ReadyResponse(status="ok", provisioning=provisioning, migrations=migrations)
