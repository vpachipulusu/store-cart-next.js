from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.me_preferences import HistoryPage, SettingsData


class PreferencesRepositoryProtocol(Protocol):
    async def get_settings(self, user_id: str) -> SettingsData: ...
    async def update_settings(
        self, user_id: str, changes: dict[str, str | bool]
    ) -> SettingsData: ...
    async def get_login_history(
        self, user_id: str, limit: int, offset: int
    ) -> HistoryPage: ...


class PreferencesService:
    def __init__(
        self, repository: PreferencesRepositoryProtocol, session: AsyncSession
    ) -> None:
        self.repository = repository
        self.session = session

    async def get_settings(self, user_id: str) -> SettingsData:
        return await self.repository.get_settings(user_id)

    async def update_settings(
        self, user_id: str, changes: dict[str, str | bool]
    ) -> SettingsData:
        if not changes or set(changes) - {
            "theme",
            "email_notifications",
            "language",
            "timezone",
        }:
            raise ValueError("Invalid settings")
        for name, value in changes.items():
            if name == "email_notifications":
                if type(value) is not bool:
                    raise ValueError("Invalid settings")
            elif not isinstance(value, str) or (
                (name == "theme" and value not in {"system", "light", "dark"})
                or (name == "language" and not 2 <= len(value) <= 5)
                or (name == "timezone" and not 1 <= len(value) <= 100)
            ):
                raise ValueError("Invalid settings")
        # Authentication and user lookup may already have opened the transaction.
        if self.session.in_transaction():
            try:
                settings = await self.repository.update_settings(user_id, changes)
                await self.session.commit()
            except Exception:
                await self.session.rollback()
                raise
            return settings
        async with self.session.begin():
            return await self.repository.update_settings(user_id, changes)

    async def get_login_history(
        self, user_id: str, limit: int, offset: int
    ) -> HistoryPage:
        if type(limit) is not int or type(offset) is not int:
            raise ValueError("Invalid pagination")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        return await self.repository.get_login_history(user_id, limit, offset)
