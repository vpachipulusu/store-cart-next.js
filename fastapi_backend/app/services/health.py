import asyncio
import logging

from alembic.util.exc import CommandError
from sqlalchemy.exc import NoResultFound, ProgrammingError

from app.core.db_errors import DATABASE_UNAVAILABLE_ERRORS, root_cause_name
from app.core.platform_schema import PlatformSchemaStatus, platform_schema_status
from app.repositories.health import HealthRepository

logger = logging.getLogger(__name__)

# Seconds the whole readiness ping (connect plus SELECT 1) may take. The connect
# timeout (db_url.CONNECT_TIMEOUT_SECONDS) does not cover a connection that stalls
# after connecting; this does, so a hung database answers 503 instead of hanging.
READINESS_TIMEOUT_SECONDS = 5.0

# What reading `alembic_version` raises on a database that was never migrated: no
# table (UndefinedTable, a ProgrammingError) or no row.
NOT_MIGRATED_ERRORS: tuple[type[BaseException], ...] = (ProgrammingError, NoResultFound)


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

    async def schema_status(self) -> PlatformSchemaStatus | None:
        """The platform schema against this build's migrations (KAN-253).

        No ``alembic_version`` table or no row counts as not migrated (pending). Any
        other database error returns None: the database is unavailable, not behind,
        so operators are not told to run migrations for an outage.
        """
        try:
            async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
                current = await self._repository.applied_revision()
        except NOT_MIGRATED_ERRORS:
            current = None
        except DATABASE_UNAVAILABLE_ERRORS as error:
            logger.error("Platform revision check failed: %s", root_cause_name(error))
            return None
        try:
            # Reading the migration scripts is file IO: keep it off the event loop.
            status = await asyncio.to_thread(platform_schema_status, current)
        except CommandError as error:
            # The migration scripts are missing or unreadable in this build.
            logger.error(
                "Platform migration scripts unreadable: %s", type(error).__name__
            )
            return None
        if status.pending:
            logger.error(
                "Platform database is behind this build: current=%s head=%s; "
                "run `alembic upgrade head`",
                status.current,
                status.head,
            )
        return status
