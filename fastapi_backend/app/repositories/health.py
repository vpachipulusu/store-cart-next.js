from sqlalchemy import text

from app.repositories.base import BaseRepository


class HealthRepository(BaseRepository):
    async def ping(self) -> bool:
        """Return True when the database answers a trivial query."""
        result = await self._session.execute(text("SELECT 1"))
        return bool(result.scalar_one() == 1)

    async def applied_revision(self) -> str | None:
        """The platform Alembic revision recorded in the database.

        The platform tree has a single head, so ``alembic_version`` holds one row.
        No table or no row raise and mean "not migrated"; several rows raise
        MultipleResultsFound, which the service reports as unavailable.
        """
        result = await self._session.execute(
            text("SELECT version_num FROM alembic_version")
        )
        value = result.scalar_one()
        return None if value is None else str(value)
