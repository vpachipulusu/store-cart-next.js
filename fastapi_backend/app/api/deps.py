"""FastAPI dependencies: where the database session provider is injected."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
)
from app.core.rate_limit import DisabledRateLimiter, RateLimiter, UpstashRateLimiter
from app.repositories.health import HealthRepository
from app.services.health import HealthService

logger = logging.getLogger(__name__)

_default_provider = DefaultSessionProvider(async_session_maker)


def get_session_provider() -> SessionProvider:
    """The one place that decides which provider repositories get.

    Tests override this dependency with a fake; per-store routing (E7) will swap
    or extend it.
    """
    return _default_provider


async def get_session(
    provider: Annotated[SessionProvider, Depends(get_session_provider)],
) -> AsyncIterator[AsyncSession]:
    async with provider.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_health_service(session: SessionDep) -> HealthService:
    return HealthService(HealthRepository(session))


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]


_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """The limiter routes and readiness use; tests override this with a fake.

    Without Upstash settings (local dev, tests) rate limiting is disabled.
    """
    global _rate_limiter
    if _rate_limiter is None:
        token = settings.UPSTASH_REDIS_REST_TOKEN
        if settings.UPSTASH_REDIS_REST_URL and token:
            _rate_limiter = UpstashRateLimiter.from_credentials(
                settings.UPSTASH_REDIS_REST_URL, token.get_secret_value()
            )
        else:
            logger.warning("Upstash Redis not configured: rate limiting is disabled")
            _rate_limiter = DisabledRateLimiter()
    return _rate_limiter
