from sqlalchemy import text

from app.repositories.base import BaseRepository


class HealthRepository(BaseRepository):
    async def ping(self) -> bool:
        """Return True when the database answers a trivial query."""
        result = await self._session.execute(text("SELECT 1"))
        return bool(result.scalar_one() == 1)
