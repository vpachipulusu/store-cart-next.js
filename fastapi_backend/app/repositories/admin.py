from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.admin_user import AdminUser
from app.models.platform.user import User


@dataclass(frozen=True)
class AdminGrant:
    user_id: str
    role: str
    permissions: Any  # raw JSONB; interpreted by core.permissions.effective_permissions


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_grant(self, uid: str) -> AdminGrant | None:
        statement = (
            select(AdminUser.user_id, AdminUser.role, AdminUser.permissions)
            .join(User, User.id == AdminUser.user_id)
            .where(User.firebase_uid == uid)
        )
        row = (await self.session.execute(statement)).one_or_none()
        return AdminGrant(row[0], row[1], row[2]) if row is not None else None
