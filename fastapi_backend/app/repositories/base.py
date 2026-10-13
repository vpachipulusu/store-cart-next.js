from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Base for repositories: holds the session it was given and never opens one."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
