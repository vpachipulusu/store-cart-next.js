from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.admin_user import AdminUser
from app.models.platform.membership import Membership, MembershipRole
from app.models.platform.user import User


@dataclass(frozen=True)
class ProfileData:
    id: str
    email: str
    email_verified: bool
    two_factor_enabled: bool
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    location: str | None
    website: str | None
    phone_number: str | None
    created_at: datetime
    is_admin: bool
    admin_role: str | None


def profile_data(user: User, admin_role: str | None) -> ProfileData:
    return ProfileData(
        user.id,
        user.email,
        user.email_verified,
        user.two_factor_enabled,
        user.display_name,
        user.bio,
        user.avatar_url,
        user.location,
        user.website,
        user.phone_number,
        user.created_at,
        admin_role is not None,
        admin_role,
    )


class MeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_profile(self, uid: str, *, lock: bool = False) -> ProfileData | None:
        # Same source require_admin authorises against: the caller's own admin_users row.
        statement = (
            select(User, AdminUser.role)
            .outerjoin(AdminUser, AdminUser.user_id == User.id)
            .where(User.firebase_uid == uid)
        )
        if lock:
            statement = statement.with_for_update(of=User)
        row = (await self.session.execute(statement)).one_or_none()
        return profile_data(row[0], row[1]) if row is not None else None

    async def update_profile(
        self, user_id: str, changes: dict[str, str | None]
    ) -> ProfileData:
        statement = (
            update(User).where(User.id == user_id).values(**changes).returning(User)
        )
        user = (await self.session.execute(statement)).scalar_one()
        role = (
            await self.session.execute(
                select(AdminUser.role).where(AdminUser.user_id == user.id)
            )
        ).scalar_one_or_none()
        return profile_data(user, role)

    async def has_owner_membership(self, user_id: str) -> bool:
        statement = (
            select(Membership.role)
            .where(Membership.user_id == user_id)
            .with_for_update()
        )
        roles = (await self.session.execute(statement)).scalars().all()
        return MembershipRole.OWNER in roles

    async def delete_user(self, user_id: str) -> None:
        await self.session.execute(delete(User).where(User.id == user_id))
