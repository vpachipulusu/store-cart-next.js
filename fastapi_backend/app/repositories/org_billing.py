from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.plans import effective_plan_key
from app.models.platform.membership import Membership, MembershipRole
from app.models.platform.organization import Organization
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class OrgBillingRecord:
    """What the billing endpoints read of an organisation (never written here, except the customer link)."""

    id: str
    name: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    stripe_current_period_end: datetime | None
    subscription_tier: str
    subscription_status: str
    stripe_cancel_at_period_end: bool = False


class OrgBillingRepository(BaseRepository):
    async def get_role(
        self, organization_id: str, user_id: str
    ) -> MembershipRole | None:
        return (
            await self._session.execute(
                select(Membership.role).where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def get(self, organization_id: str) -> OrgBillingRecord | None:
        organization = (
            await self._session.execute(
                select(Organization).where(Organization.id == organization_id)
            )
        ).scalar_one_or_none()
        if organization is None:
            return None
        return OrgBillingRecord(
            organization.id,
            organization.name,
            organization.stripe_customer_id,
            organization.stripe_subscription_id,
            organization.stripe_price_id,
            organization.stripe_current_period_end,
            # The plan in force: the Stripe tier or a higher, unexpired admin grant (KAN-48).
            effective_plan_key(
                organization.subscription_tier,
                organization.granted_plan,
                organization.granted_until,
                datetime.now(UTC),
            ).value,
            organization.subscription_status,
            organization.stripe_cancel_at_period_end,
        )

    async def link_customer(self, organization_id: str, customer_id: str) -> str:
        """Save the Stripe customer id if none is saved yet; return the id now saved.

        The conditional update keeps the first link when two requests race, so one
        organisation never ends up with two customers.
        """
        await self._session.execute(
            update(Organization)
            .where(
                Organization.id == organization_id,
                Organization.stripe_customer_id.is_(None),
            )
            .values(stripe_customer_id=customer_id)
        )
        saved = (
            await self._session.execute(
                select(Organization.stripe_customer_id).where(
                    Organization.id == organization_id
                )
            )
        ).scalar_one()
        if saved is None:
            raise LookupError("organization has no Stripe customer")
        return saved
