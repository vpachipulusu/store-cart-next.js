import logging

from app.core.db_errors import DATABASE_UNAVAILABLE_ERRORS, root_cause_name
from app.repositories.health import HealthRepository

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    async def is_database_ready(self) -> bool:
        """True when the database answers.

        A database or connection error (refused, unreachable, timed out, rejected by
        the server) is logged and reported as not ready, so the route answers 503.
        """
        try:
            return await self._repository.ping()
        except DATABASE_UNAVAILABLE_ERRORS as error:
            # The type only, no message or traceback: driver messages can name the
            # host and database user. An auth failure (InvalidPasswordError) stays
            # distinguishable from an outage (ConnectionRefusedError, TimeoutError).
            logger.error("Database readiness check failed: %s", root_cause_name(error))
            return False
