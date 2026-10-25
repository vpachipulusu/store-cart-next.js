"""Session factory for a store's own database (KAN-54, ADR-005).

``get_store_session(store_id)`` is the only way to reach a store database. It looks the
store up on the platform database, decrypts its connection string (KAN-53), opens an
engine for that store alone and yields one session. The engine uses ``NullPool``: on
serverless (Vercel, Neon pooled endpoints) connections must not outlive the request,
so the engine is disposed when the context exits. Nothing is cached across calls.

The plaintext connection string never reaches a log line or an exception message;
failures carry only the store id.

KAN-238: a decrypted string must name the store's own database, ``store_<id>``, and,
when it signs in as a store role, that store's role. A string still on the shared
provisioning role (a store not yet moved by ``commands.backfill_store_roles``) is
allowed with a warning. ``open_admin_connection`` is the provisioning role's way into a
store database; it lives here because engines may only be built in this module.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
    build_engine,
)
from app.core.store_crypto import StoreSecretUnavailable
from app.models.platform.store import Store
from app.services import store_secrets
from app.services.store_roles import STORE_NAME_PREFIX

logger = logging.getLogger("storecart.store_sessions")


class StoreSessionError(Exception):
    """A store database session could not be opened. Never carries secrets."""

    def __init__(self, store_id: str) -> None:
        super().__init__(f"{type(self).__name__}: store {store_id}")
        self.store_id = store_id


class StoreNotFound(StoreSessionError):
    """No store has this id."""


class StoreDatabaseNotConfigured(StoreSessionError):
    """The store has no connection string yet (not provisioned)."""


class StoreDatabaseUnavailable(StoreSessionError):
    """The stored connection string cannot be decrypted or used."""


async def _load_connection_string(provider: SessionProvider, store_id: str) -> str:
    async with provider.session() as platform_session:
        store = (
            await platform_session.execute(select(Store).where(Store.id == store_id))
        ).scalar_one_or_none()
        if store is None:
            raise StoreNotFound(store_id)
        try:
            connection_string = store_secrets.reveal_connection_string(store)
        except StoreSecretUnavailable:
            raise StoreDatabaseUnavailable(store_id) from None
    if connection_string is None:
        raise StoreDatabaseNotConfigured(store_id)
    return connection_string


def _check_target(store_id: str, connection_string: str) -> None:
    """Refuse a string for another store's database or role (no secret in the error)."""
    try:
        url = make_url(connection_string)
    except (ArgumentError, ValueError):
        logger.error(
            "store connection string is malformed", extra={"store_id": store_id}
        )
        raise StoreDatabaseUnavailable(store_id) from None
    expected = f"{STORE_NAME_PREFIX}{store_id}"
    user = url.username or ""
    if url.database != expected or (
        user.startswith(STORE_NAME_PREFIX) and user != expected
    ):
        logger.error(
            "store connection string targets another store",
            extra={"store_id": store_id},
        )
        raise StoreDatabaseUnavailable(store_id)
    if user != expected:
        logger.warning(
            "store still uses the shared database role; run backfill_store_roles",
            extra={"store_id": store_id},
        )


@asynccontextmanager
async def open_store_session(
    store_id: str, provider: SessionProvider
) -> AsyncIterator[AsyncSession]:
    """Like ``get_store_session`` with an explicit platform session provider."""
    connection_string = await _load_connection_string(provider, store_id)
    _check_target(store_id, connection_string)
    try:
        engine = build_engine(connection_string)
    except (ArgumentError, ValueError):
        # Malformed URL: the SQLAlchemy message can echo parts of it.
        logger.error("store engine could not be built", extra={"store_id": store_id})
        raise StoreDatabaseUnavailable(store_id) from None
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


def get_store_session(store_id: str) -> AbstractAsyncContextManager[AsyncSession]:
    """Async context manager yielding a session on this store's database only."""
    return open_store_session(store_id, DefaultSessionProvider(async_session_maker))


@asynccontextmanager
async def open_admin_connection(
    connection_string: str,
) -> AsyncIterator[AsyncConnection]:
    """One transaction on a store database as the provisioning role (KAN-238).

    For the provisioners and the role backfill only; request code uses
    ``get_store_session``. Commits when the block exits cleanly. A malformed URL raises
    ``ValueError`` with no detail (the SQLAlchemy message can echo the URL).
    """
    try:
        engine = build_engine(connection_string)
    except (ArgumentError, ValueError):
        raise ValueError("unusable admin connection string") from None
    try:
        async with engine.begin() as connection:
            yield connection
    finally:
        await engine.dispose()
