from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.api.deps import HealthServiceDep, get_rate_limiter
from app.core.rate_limit import RateLimiter

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness check. Touches no database or other dependency."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def readiness_check(
    response: Response,
    service: HealthServiceDep,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> HealthResponse:
    """Readiness: 200 when the database (and Redis, if configured) answer, else 503."""
    if await service.is_database_ready() and await limiter.ping():
        return HealthResponse(status="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable")
