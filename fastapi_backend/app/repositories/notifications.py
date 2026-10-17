from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, and_, delete, func, select, update

from app.models.platform.user import Notification
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class NotificationData:
    id: str
    type: str
    title: str
    message: str
    read: bool
    link: str | None
    organization_id: str | None
    store_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class NotificationScope:
    """Optional narrowing by organisation and/or store, always within one user's rows."""

    organization_id: str | None = None
    store_id: str | None = None


@dataclass(frozen=True)
class NotificationPage:
    notifications: list[NotificationData]
    total_count: int
    unread_count: int


def notification_data(row: Notification) -> NotificationData:
    return NotificationData(
        row.id,
        row.type,
        row.title,
        row.message,
        row.read,
        row.link,
        row.organization_id,
        row.store_id,
        row.created_at,
    )


def _owned_by(user_id: str, scope: NotificationScope) -> list[ColumnElement[bool]]:
    """Every query starts from the caller's own rows; the scope only narrows them."""
    conditions = [Notification.user_id == user_id]
    if scope.organization_id is not None:
        conditions.append(Notification.organization_id == scope.organization_id)
    if scope.store_id is not None:
        conditions.append(Notification.store_id == scope.store_id)
    return conditions


class NotificationsRepository(BaseRepository):
    async def list_for_user(
        self,
        user_id: str,
        scope: NotificationScope,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> NotificationPage:
        scoped = _owned_by(user_id, scope)
        listed = [*scoped, Notification.read.is_(False)] if unread_only else scoped
        counts = await self._session.execute(
            select(
                func.count(),
                func.count().filter(Notification.read.is_(False)),
            ).where(and_(*scoped))
        )
        total, unread = counts.one()
        result = await self._session.execute(
            select(Notification)
            .where(and_(*listed))
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return NotificationPage(
            [notification_data(row) for row in result.scalars().all()],
            int(unread if unread_only else total),
            int(unread),
        )

    async def mark_read(
        self, user_id: str, notification_id: str
    ) -> NotificationData | None:
        result = await self._session.execute(
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .values(read=True)
            .returning(Notification)
        )
        row = result.scalar_one_or_none()
        return None if row is None else notification_data(row)

    async def mark_all_read(self, user_id: str, scope: NotificationScope) -> int:
        result = await self._session.execute(
            update(Notification)
            .where(*_owned_by(user_id, scope), Notification.read.is_(False))
            .values(read=True)
        )
        return int(cast("CursorResult[Any]", result).rowcount)

    async def delete(self, user_id: str, notification_id: str) -> bool:
        result = await self._session.execute(
            delete(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .returning(Notification.id)
        )
        return result.scalar_one_or_none() is not None
