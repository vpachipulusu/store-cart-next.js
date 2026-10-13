import logging

from sqlalchemy.exc import SQLAlchemyError

from app.repositories.health import HealthRepository

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    async def is_database_ready(self) -> bool:
        """True when the database answers; a database error is logged, not raised."""
        try:
            return await self._repository.ping()
        except SQLAlchemyError:
            logger.exception("Database readiness check failed")
            return False
