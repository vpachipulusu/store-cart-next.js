"""Migrate store databases to the head of the ``alembic_store`` tree (KAN-57, ADR-005).

``migrate_store(store_id)`` brings one store database to head and records the result in
``stores.schema_version``; the provisioning job (KAN-56) and the tenant isolation tests
(KAN-58) call it. ``migrate_active_stores`` runs it for every ACTIVE store in batches and
stops at the first failure; ``commands.migrate_stores`` is its command line.

Rules:

* The store database is reached only through ``open_store_session`` (KAN-54), so the
  connection string never leaves ``store_sessions``. The Alembic environment receives the
  open connection and builds no engine of its own.
* Failures carry the store id and an exception class name, never a connection string or
  driver message.
* A per-database advisory lock serialises two runners on the same store. The lock, the
  DDL and the version stamp share one transaction, so a failed revision leaves the store
  at its previous version.
* ``schema_version`` is the number of store revisions applied. It is written after the
  store database is committed; if that write fails the next run repairs it, because the
  upgrade itself is idempotent.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Connection, CursorResult
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.database import (
    DefaultSessionProvider,
    SessionProvider,
    async_session_maker,
)
from app.models.platform.store import Store, StoreStatus
from app.services.store_sessions import StoreNotFound, open_store_session

logger = logging.getLogger("storecart.store_migrations")

STORE_SCRIPT_LOCATION = Path(__file__).resolve().parents[2] / "alembic_store"
VERSION_TABLE = "store_alembic_version"
DEFAULT_BATCH_SIZE = 50
# Arbitrary constant: the key of the advisory lock that serialises migrations per database.
# No other code may take an advisory lock with this key.
_ADVISORY_LOCK_KEY = 5_735_701
_SQLSTATE = re.compile(r"[0-9A-Z]{5}")
MAX_BATCH_SIZE = 500
# Waiting for another runner on the same store (a second run, or the provisioning job) is
# not a DDL lock wait: it is polled with pg_try_advisory_xact_lock for up to this long.
ADVISORY_LOCK_WAIT_SECONDS = 900.0
ADVISORY_POLL_SECONDS = 0.5
# Bounds for the DDL itself, applied only after the advisory lock is held.
LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "10min"


class StoreSchemaAhead(Exception):
    """The store database is stamped with a revision this build does not know."""


class AdvisoryLockTimeout(Exception):
    """Another runner held the store's migration lock for the whole wait."""


def safe_reason(exc: BaseException) -> str:
    """Class name plus SQLSTATE when the driver gives one. Never ``str(exc)``."""
    reason = type(exc).__name__
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if isinstance(sqlstate, str) and _SQLSTATE.fullmatch(sqlstate):
        reason = f"{reason} sqlstate={sqlstate}"
    return reason


class StoreMigrationFailed(Exception):
    """A store could not be migrated. Never carries a connection string."""

    def __init__(self, store_id: str, reason: str) -> None:
        super().__init__(f"{type(self).__name__}: store {store_id} ({reason})")
        self.store_id = store_id
        self.reason = reason


class StoreVersionNotRecorded(StoreMigrationFailed):
    """The store database is migrated but ``stores.schema_version`` was not updated."""


@dataclass(frozen=True)
class StoreMigrationResult:
    store_id: str
    schema_version: int


@dataclass(frozen=True)
class MigrationReport:
    migrated: tuple[StoreMigrationResult, ...] = ()
    # Stores that were not ACTIVE and so were left alone, by status.
    skipped: Mapping[StoreStatus, int] = field(default_factory=dict)
    failed_store_id: str | None = None
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failed_store_id is None


def _alembic_config(script_location: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(script_location))
    config.attributes["version_table"] = VERSION_TABLE
    return config


def _upgrade_to_head(connection: Connection, script_location: Path) -> int:
    """Runs inside ``AsyncConnection.run_sync``; returns the resulting schema version."""
    config = _alembic_config(script_location)
    scripts = ScriptDirectory.from_config(config)
    context = MigrationContext.configure(
        connection, opts={"version_table": VERSION_TABLE}
    )
    stamped = context.get_current_revision()
    if stamped is not None:
        try:
            scripts.get_revision(stamped)
        except CommandError:
            # A newer build already migrated this store (rolling deploy): never go back.
            raise StoreSchemaAhead from None
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    current = MigrationContext.configure(
        connection, opts={"version_table": VERSION_TABLE}
    ).get_current_revision()
    if current is None:
        return 0
    # The count assumes a linear history; the single-head unit test keeps it that way.
    return len(list(scripts.walk_revisions(base="base", head=current)))


async def _prepare_connection(connection: AsyncConnection) -> None:
    """Take the per-database advisory lock, then bound the DDL that follows.

    The lock is polled (``pg_try_advisory_xact_lock``) so waiting for another runner has
    its own budget and never trips the DDL ``lock_timeout``. Both settings and the lock are
    transaction scoped, so they are safe behind PgBouncer transaction pooling. The
    ahead-of-code check that follows relies on READ COMMITTED (the default; every
    statement sees a runner that committed while we waited): do not raise the isolation
    level of store engines.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ADVISORY_LOCK_WAIT_SECONDS
    while True:
        acquired = (
            await connection.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": _ADVISORY_LOCK_KEY},
            )
        ).scalar_one()
        if acquired:
            break
        if loop.time() >= deadline:
            raise AdvisoryLockTimeout
        await asyncio.sleep(ADVISORY_POLL_SECONDS)
    # A stuck revision must fail this store (and stop the run), not hang it.
    for name, value in (
        ("lock_timeout", LOCK_TIMEOUT),
        ("statement_timeout", STATEMENT_TIMEOUT),
    ):
        await connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": name, "value": value},
        )


async def migrate_store(
    store_id: str,
    provider: SessionProvider | None = None,
    *,
    script_location: Path = STORE_SCRIPT_LOCATION,
) -> int:
    """Apply pending store migrations to one store database; return its schema version.

    Idempotent: with nothing pending it changes nothing but still records the version.
    Does not look at ``Store.status``, so the provisioning job can migrate a store that is
    still PROVISIONING. Raises StoreMigrationFailed (store id and error class only), or its
    subclass StoreVersionNotRecorded when the store was migrated but the platform write
    failed (re-run to repair).
    """
    platform = provider or DefaultSessionProvider(async_session_maker)
    try:
        async with open_store_session(store_id, platform) as session:
            connection = await session.connection()
            await _prepare_connection(connection)
            version = await connection.run_sync(_upgrade_to_head, script_location)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - includes StoreSessionError, collapsed too
        raise _failure(StoreMigrationFailed, store_id, exc) from None
    try:
        await _record_version(platform, store_id, version)
    except Exception as exc:  # noqa: BLE001
        raise _failure(StoreVersionNotRecorded, store_id, exc) from None
    return version


async def _record_version(
    provider: SessionProvider, store_id: str, version: int
) -> None:
    async with provider.session() as session:
        # GREATEST: an older build running late must never lower a newer build's stamp.
        result = await session.execute(
            update(Store)
            .where(Store.id == store_id)
            .values(schema_version=func.greatest(Store.schema_version, version))
        )
        if cast("CursorResult[Any]", result).rowcount != 1:
            raise StoreNotFound(store_id)
        await session.commit()


def _failure(
    kind: type[StoreMigrationFailed], store_id: str, exc: Exception
) -> StoreMigrationFailed:
    """Log and build a safe failure: class name and SQLSTATE only (never str(exc))."""
    reason = safe_reason(exc)
    logger.error("%s: %s", kind.__name__, reason, extra={"store_id": store_id})
    return kind(store_id, reason)


async def _active_store_pages(
    provider: SessionProvider, batch_size: int
) -> AsyncIterator[list[str]]:
    """Ids of ACTIVE stores in id order, ``batch_size`` at a time (keyset paging)."""
    last_id = ""
    while True:
        async with provider.session() as session:
            ids = list(
                (
                    await session.execute(
                        select(Store.id)
                        .where(Store.status == StoreStatus.ACTIVE, Store.id > last_id)
                        .order_by(Store.id)
                        .limit(batch_size)
                    )
                ).scalars()
            )
        if not ids:
            return
        yield ids
        last_id = ids[-1]


async def _count_skipped(provider: SessionProvider) -> dict[StoreStatus, int]:
    async with provider.session() as session:
        rows = (
            await session.execute(
                select(Store.status, func.count())
                .where(Store.status != StoreStatus.ACTIVE)
                .group_by(Store.status)
            )
        ).all()
    return {StoreStatus(status): count for status, count in rows}


async def migrate_pages(
    pages: AsyncIterator[list[str]],
    migrate: Callable[[str], Awaitable[int]],
) -> tuple[tuple[StoreMigrationResult, ...], StoreMigrationFailed | None]:
    """Migrate page after page; stop at the first failure (later stores are untouched)."""
    migrated: list[StoreMigrationResult] = []
    async for page in pages:
        for store_id in page:
            try:
                version = await migrate(store_id)
            except StoreMigrationFailed as failure:
                return tuple(migrated), failure
            migrated.append(StoreMigrationResult(store_id, version))
    return tuple(migrated), None


async def migrate_active_stores(
    provider: SessionProvider | None = None,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    script_location: Path = STORE_SCRIPT_LOCATION,
) -> MigrationReport:
    """Migrate every ACTIVE store in batches, stopping at the first failure."""
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    platform = provider or DefaultSessionProvider(async_session_maker)

    async def migrate(store_id: str) -> int:
        return await migrate_store(store_id, platform, script_location=script_location)

    skipped = await _count_skipped(platform)
    migrated, failure = await migrate_pages(
        _active_store_pages(platform, batch_size), migrate
    )
    return MigrationReport(
        migrated=migrated,
        skipped=skipped,
        failed_store_id=failure.store_id if failure else None,
        failure_reason=failure.reason if failure else None,
    )
