import logging

from app.core.database import DATABASE_UNAVAILABLE_ERRORS
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
        except DATABASE_UNAVAILABLE_ERRORS:
            logger.exception("Database readiness check failed")
            return False
