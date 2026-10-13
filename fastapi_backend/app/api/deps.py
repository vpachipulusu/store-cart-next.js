"""FastAPI dependencies: where the database session provider is injected."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
)
from app.repositories.health import HealthRepository
from app.services.health import HealthService

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
