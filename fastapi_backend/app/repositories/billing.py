from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.models.platform.organization import Organization
from app.models.platform.stripe_event import StripeEvent


@dataclass(frozen=True)
class BillingState:
    """The organisation's subscription fields the webhook reads and writes."""

    organization_id: str
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    stripe_current_period_end: datetime | None
    stripe_subscription_event_at: datetime | None
    subscription_tier: str
    subscription_status: str


@dataclass(frozen=True)
class BillingChange:
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    stripe_current_period_end: datetime | None
    stripe_subscription_event_at: datetime
    subscription_tier: str
    subscription_status: str
    stripe_cancel_at_period_end: bool = False


class StripeEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self, stripe_event_id: str, event_type: str, created: datetime
    ) -> bool:
        """Insert the event id in the caller's transaction; False if already recorded.

        A concurrent delivery of the same id blocks on the unique index until the
        first transaction ends: it then sees a duplicate after a commit, or inserts
        itself after a rollback.
        """
        statement = (
            pg_insert(StripeEvent)
            .values(
                id=new_id(),
                stripe_event_id=stripe_event_id,
                type=event_type,
                stripe_created_at=created,
            )
            .on_conflict_do_nothing(index_elements=[StripeEvent.stripe_event_id])
            .returning(StripeEvent.id)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None


class OrganizationBillingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_update(
        self, *, subscription_id: str | None, customer_id: str | None
    ) -> BillingState | None:
        """Find the organisation by its subscription, else its customer, and lock the row."""
        for column, value in (
            (Organization.stripe_subscription_id, subscription_id),
            (Organization.stripe_customer_id, customer_id),
        ):
            if not value:
                continue
            organization = (
                await self.session.execute(
                    select(Organization).where(column == value).with_for_update()
                )
            ).scalar_one_or_none()
            if organization is not None:
                return BillingState(
                    organization.id,
                    organization.stripe_subscription_id,
                    organization.stripe_price_id,
                    organization.stripe_current_period_end,
                    organization.stripe_subscription_event_at,
                    organization.subscription_tier,
                    organization.subscription_status,
                )
        return None

    async def apply(self, organization_id: str, change: BillingChange) -> None:
        await self.session.execute(
            update(Organization)
            .where(Organization.id == organization_id)
            .values(
                stripe_subscription_id=change.stripe_subscription_id,
                stripe_price_id=change.stripe_price_id,
                stripe_current_period_end=change.stripe_current_period_end,
                stripe_subscription_event_at=change.stripe_subscription_event_at,
                subscription_tier=change.subscription_tier,
                subscription_status=change.subscription_status,
                stripe_cancel_at_period_end=change.stripe_cancel_at_period_end,
            )
        )
