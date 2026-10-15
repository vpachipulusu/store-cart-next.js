"""Read access to the platform ``app_settings`` table (KAN-205)."""

from typing import Any

from sqlalchemy import select

from app.models.platform.app_setting import AppSetting
from app.repositories.base import BaseRepository


class AppSettingsRepository(BaseRepository):
    async def get_value(self, key: str) -> Any | None:
        """The stored JSON value for ``key``, or None when the row is missing."""
        return (
            await self._session.execute(
                select(AppSetting.value).where(AppSetting.key == key)
            )
        ).scalar_one_or_none()
