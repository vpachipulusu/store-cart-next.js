from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.platform.user import LoginHistory, UserSettings
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class SettingsData:
    theme: str
    email_notifications: bool
    language: str
    timezone: str


@dataclass(frozen=True)
class HistoryEntry:
    id: str
    ip_address: str | None
    user_agent: str | None
    location: str | None
    login_at: datetime
    successful: bool


@dataclass(frozen=True)
class HistoryPage:
    login_history: list[HistoryEntry]
    total_count: int


def settings_data(settings: UserSettings) -> SettingsData:
    return SettingsData(
        settings.theme,
        settings.email_notifications,
        settings.language,
        settings.timezone,
    )


class PreferencesRepository(BaseRepository):
    async def get_settings(self, user_id: str) -> SettingsData:
        result = await self._session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            return SettingsData("system", True, "en", "UTC")
        return settings_data(settings)

    async def update_settings(
        self, user_id: str, changes: dict[str, str | bool]
    ) -> SettingsData:
        statement = insert(UserSettings).values(user_id=user_id, **changes)
        upsert = statement.on_conflict_do_update(
            index_elements=[UserSettings.user_id],
            set_={**changes, "updated_at": func.now()},
        ).returning(UserSettings)
        result = await self._session.execute(upsert)
        return settings_data(result.scalar_one())

    async def get_login_history(
        self, user_id: str, limit: int, offset: int
    ) -> HistoryPage:
        count_result = await self._session.execute(
            select(func.count())
            .select_from(LoginHistory)
            .where(LoginHistory.user_id == user_id)
        )
        result = await self._session.execute(
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.login_at.desc(), LoginHistory.id.desc())
            .limit(limit)
            .offset(offset)
        )
        entries = [
            HistoryEntry(
                row.id,
                row.ip_address,
                row.user_agent,
                row.location,
                row.login_at,
                row.successful,
            )
            for row in result.scalars().all()
        ]
        return HistoryPage(entries, int(count_result.scalar_one()))
