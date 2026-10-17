from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notifications import (
    NotificationData,
    NotificationPage,
    NotificationScope,
)


class NotificationNotFound(Exception):
    """No notification with this id belongs to the caller (missing or someone else's)."""


class NotificationsRepositoryProtocol(Protocol):
    async def list_for_user(
        self,
        user_id: str,
        scope: NotificationScope,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> NotificationPage: ...
    async def mark_read(
        self, user_id: str, notification_id: str
    ) -> NotificationData | None: ...
    async def mark_all_read(self, user_id: str, scope: NotificationScope) -> int: ...
    async def delete(self, user_id: str, notification_id: str) -> bool: ...


class NotificationsService:
    """Every operation is keyed by the authenticated user id, so a caller can only ever
    read or change their own notifications."""

    def __init__(
        self, repository: NotificationsRepositoryProtocol, session: AsyncSession
    ) -> None:
        self.repository = repository
        self.session = session

    async def list_notifications(
        self,
        user_id: str,
        scope: NotificationScope,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> NotificationPage:
        return await self.repository.list_for_user(
            user_id, scope, unread_only, limit, offset
        )

    async def mark_read(self, user_id: str, notification_id: str) -> NotificationData:
        try:
            notification = await self.repository.mark_read(user_id, notification_id)
            if notification is None:
                raise NotificationNotFound
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return notification

    async def mark_all_read(self, user_id: str, scope: NotificationScope) -> int:
        try:
            updated = await self.repository.mark_all_read(user_id, scope)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return updated

    async def delete(self, user_id: str, notification_id: str) -> None:
        try:
            if not await self.repository.delete(user_id, notification_id):
                raise NotificationNotFound
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
