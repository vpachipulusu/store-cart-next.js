"""FastAPI dependencies: where the database session provider is injected."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException
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
from app.services.media_uploads import (
    Boto3UploadSigner,
    MediaUploadService,
)

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


_media_upload_service: MediaUploadService | None = None


def get_media_upload_service() -> MediaUploadService:
    """The one place the boto3 signer is built; tests override this dependency.

    Answers 503 when the R2 settings are unset.
    """
    global _media_upload_service
    if _media_upload_service is None:
        secret = settings.R2_SECRET_ACCESS_KEY
        if (
            not settings.R2_ACCOUNT_ID
            or not settings.R2_ACCESS_KEY_ID
            or secret is None
            or not settings.R2_BUCKET_NAME
            or not settings.R2_PUBLIC_BASE_URL
        ):
            raise HTTPException(503, "Service temporarily unavailable")
        _media_upload_service = MediaUploadService(
            Boto3UploadSigner(
                account_id=settings.R2_ACCOUNT_ID,
                access_key_id=settings.R2_ACCESS_KEY_ID,
                secret_access_key=secret.get_secret_value(),
                bucket=settings.R2_BUCKET_NAME,
            ),
            settings.R2_PUBLIC_BASE_URL,
        )
    return _media_upload_service
