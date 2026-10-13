from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.api.deps import HealthServiceDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness check. Touches no database or other dependency."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def readiness_check(
    response: Response, service: HealthServiceDep
) -> HealthResponse:
    """Readiness check: 200 when the database answers, 503 otherwise."""
    if await service.is_database_ready():
        return HealthResponse(status="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable")
