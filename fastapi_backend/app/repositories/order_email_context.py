"""Platform reads for order emails (KAN-81): the store's name and who gets the new-order alert."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.membership import Membership, MembershipRole
from app.models.platform.store import Store
from app.models.platform.user import User, UserSettings

ALERT_ROLES = (MembershipRole.OWNER, MembershipRole.ADMIN)


@dataclass(frozen=True)
class StoreEmailContext:
    name: str
    organization_id: str


@dataclass(frozen=True)
class AlertRecipient:
    user_id: str
    email: str


class OrderEmailContextRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def store(self, store_id: str) -> StoreEmailContext | None:
        row = (
            await self._session.execute(
                select(Store.name, Store.organization_id).where(Store.id == store_id)
            )
        ).first()
        return StoreEmailContext(row.name, row.organization_id) if row else None

    async def alert_recipients(self, organization_id: str) -> list[AlertRecipient]:
        """OWNER and ADMIN members with a verified email who have not turned email off."""
        result = await self._session.execute(
            select(User.id, User.email)
            .join(Membership, Membership.user_id == User.id)
            .outerjoin(UserSettings, UserSettings.user_id == User.id)
            .where(
                Membership.organization_id == organization_id,
                Membership.role.in_(ALERT_ROLES),
                User.email_verified.is_(True),
                func.coalesce(UserSettings.email_notifications, True).is_(True),
            )
            .order_by(User.id)
        )
        return [AlertRecipient(row.id, row.email) for row in result]
