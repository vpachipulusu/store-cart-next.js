from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol
from urllib.parse import urlparse

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

parsed_db_url = urlparse(settings.DATABASE_URL)

async_db_connection_url = (
    f"postgresql+asyncpg://{parsed_db_url.username}:{parsed_db_url.password}@"
    f"{parsed_db_url.hostname}{':' + str(parsed_db_url.port) if parsed_db_url.port else ''}"
    f"{parsed_db_url.path}"
)

# Disable connection pooling for serverless environments like Vercel
engine = create_async_engine(async_db_connection_url, poolclass=NullPool)

async_session_maker = async_sessionmaker(
    engine, expire_on_commit=settings.EXPIRE_ON_COMMIT
)


class SessionProvider(Protocol):
    """Hands out database sessions to repositories (ADR-004, ADR-005).

    Repositories never create sessions: they receive one from a provider.
    Per-store routing (E7) plugs in by supplying another implementation of this
    interface (for example one that picks a store database from a grant), without
    changing any repository.
    """

    def session(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Open a session; it is closed when the context exits."""


class DefaultSessionProvider:
    """Sessions on the platform database, one per request (NullPool, no reuse)."""

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._maker() as session:
            yield session
