import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import NoResultFound, ProgrammingError

from app.core.db_errors import DATABASE_UNAVAILABLE_ERRORS, root_cause_name
from app.core.platform_schema import PlatformSchemaStatus, platform_schema_status
from app.repositories.health import HealthRepository

logger = logging.getLogger(__name__)

# Seconds the whole readiness check (connect, SELECT 1 and the revision read) may
# take. The connect timeout (db_url.CONNECT_TIMEOUT_SECONDS) does not cover a
# connection that stalls after connecting; this does, so a hung database answers
# 503 instead of hanging.
READINESS_TIMEOUT_SECONDS = 5.0

# Postgres "undefined_table": no `alembic_version`, the database was never migrated.
UNDEFINED_TABLE_SQLSTATE = "42P01"

ReadinessState = Literal["ok", "unavailable", "migrations_pending"]


@dataclass(frozen=True)
class Readiness:
    state: ReadinessState
    # None when the database could not be checked (unavailable).
    schema: PlatformSchemaStatus | None = None


def _is_undefined_table(error: BaseException) -> bool:
    """True when the driver error under ``error`` is SQLSTATE 42P01 (undefined table)."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "sqlstate", None) == UNDEFINED_TABLE_SQLSTATE:
            return True
        orig = getattr(current, "orig", None)
        current = orig if isinstance(orig, BaseException) else current.__cause__
    return False


class HealthService:
    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    async def is_database_ready(self) -> bool:
        """True when the database answers.

        A database or connection error (refused, unreachable, timed out, rejected by
        the server, or no answer within READINESS_TIMEOUT_SECONDS) is logged and
        reported as not ready, so the route answers 503.
        """
        try:
            async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
                return await self._repository.ping()
        except DATABASE_UNAVAILABLE_ERRORS as error:
            # The type only, no message or traceback: driver messages can name the
            # host and database user. An auth failure (InvalidPasswordError) stays
            # distinguishable from an outage (ConnectionRefusedError, TimeoutError).
            logger.error("Database readiness check failed: %s", root_cause_name(error))
            return False

    async def readiness(self) -> Readiness:
        """The database answers and is at this build's platform revision (KAN-253).

        One time budget covers the ping and the revision read. Only a missing
        ``alembic_version`` table (SQLSTATE 42P01) or an empty one means "migrations
        pending"; any other error (several rows, permission denied, connection lost)
        is "unavailable", so operators are not told to migrate during an outage.
        """
        try:
            async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
                if not await self._repository.ping():
                    return Readiness("unavailable")
                current = await self._applied_revision()
        except DATABASE_UNAVAILABLE_ERRORS as error:
            logger.error("Database readiness check failed: %s", root_cause_name(error))
            return Readiness("unavailable")
        schema = platform_schema_status(current)
        if not schema.pending:
            return Readiness("ok", schema)
        logger.error(
            "Platform database is behind this build: current=%s head=%s; "
            "run `alembic upgrade head`",
            schema.current,
            schema.head,
        )
        return Readiness("migrations_pending", schema)

    async def _applied_revision(self) -> str | None:
        try:
            return await self._repository.applied_revision()
        except NoResultFound:
            return None
        except ProgrammingError as error:
            if _is_undefined_table(error):
                return None
            raise
