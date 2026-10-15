import asyncio
import logging

from app.core.db_errors import DATABASE_UNAVAILABLE_ERRORS, root_cause_name
from app.repositories.health import HealthRepository

logger = logging.getLogger(__name__)

# Seconds the whole readiness ping (connect plus SELECT 1) may take. The connect
# timeout (db_url.CONNECT_TIMEOUT_SECONDS) does not cover a connection that stalls
# after connecting; this does, so a hung database answers 503 instead of hanging.
READINESS_TIMEOUT_SECONDS = 5.0


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
