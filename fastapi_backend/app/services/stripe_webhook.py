"""Stripe Billing webhook processing (KAN-44).

Each Stripe event is applied at most once: the event id is inserted and the
organisation updated in one transaction, committed here. A handler that fails
rolls both back, so the event is not marked processed and Stripe's retry runs it
again. Events older than the last one applied to an organisation are recorded but
do not change it, so a late delivery never downgrades newer state.

Logs carry event and organisation ids only, never the payload.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import PlanKey
from app.repositories.billing import BillingChange, BillingState

logger = logging.getLogger("storecart.stripe_webhook")

SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)
CREATED_EVENT = "customer.subscription.created"
DELETED_EVENT = "customer.subscription.deleted"
# Stripe subscription statuses. Paying (or in the retry grace period) keeps the plan.
ENTITLED_STATUSES = frozenset({"active", "trialing", "past_due"})
ENDED_STATUSES = frozenset({"canceled", "unpaid", "incomplete_expired", "paused"})
MAX_STATUS_LENGTH = 32


class WebhookOutcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    UNMATCHED = "unmatched"


class MalformedEvent(Exception):
    """The event is missing a field this service needs."""


class EventRepository(Protocol):
    async def claim(
        self, stripe_event_id: str, event_type: str, created: datetime
    ) -> bool: ...


class OrganizationRepository(Protocol):
    async def get_for_update(
        self, *, subscription_id: str | None, customer_id: str | None
    ) -> BillingState | None: ...
    async def apply(self, organization_id: str, change: BillingChange) -> None: ...


@dataclass(frozen=True)
class SubscriptionData:
    subscription_id: str
    customer_id: str | None
    status: str
    price_id: str | None
    period_end: datetime | None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _first_item(subscription: Mapping[str, Any]) -> Mapping[str, Any]:
    items = subscription.get("items")
    data = items.get("data") if isinstance(items, Mapping) else None
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return data[0]
    return {}


def parse_subscription(subscription: Mapping[str, Any]) -> SubscriptionData:
    subscription_id = _text(subscription.get("id"))
    status = _text(subscription.get("status"))
    if subscription_id is None or status is None:
        raise MalformedEvent
    item = _first_item(subscription)
    price = item.get("price")
    customer = subscription.get("customer")
    if isinstance(customer, Mapping):
        customer = customer.get("id")
    # The period end is on the subscription in older API versions, on the item in newer.
    period_end = _timestamp(subscription.get("current_period_end")) or _timestamp(
        item.get("current_period_end")
    )
    return SubscriptionData(
        subscription_id=subscription_id,
        customer_id=_text(customer),
        status=status[:MAX_STATUS_LENGTH],
        price_id=_text(price.get("id")) if isinstance(price, Mapping) else None,
        period_end=period_end,
    )


def _tier_for(
    data: SubscriptionData, current: BillingState, prices: Mapping[str, PlanKey]
) -> str:
    if data.status not in ENTITLED_STATUSES:
        return current.subscription_tier
    plan = prices.get(data.price_id) if data.price_id else None
    if plan is None:
        logger.warning(
            "stripe subscription price not mapped to a plan",
            extra={"organization_id": current.organization_id},
        )
        return current.subscription_tier
    return plan.value


def plan_change(
    event_type: str,
    created: datetime,
    data: SubscriptionData,
    current: BillingState,
    prices: Mapping[str, PlanKey],
) -> BillingChange | None:
    """The change to store, or None when the event must not touch the organisation."""
    if (
        current.stripe_subscription_event_at is not None
        and created < current.stripe_subscription_event_at
    ):
        return None
    deleted = event_type == DELETED_EVENT
    ended = deleted or data.status in ENDED_STATUSES
    other = (
        current.stripe_subscription_id is not None
        and current.stripe_subscription_id != data.subscription_id
    )
    if other and (ended or data.status not in ENTITLED_STATUSES):
        # Only a paying subscription may replace the current one: an old one ending,
        # or a new one that is still incomplete, must not downgrade or hide it.
        return None
    if (
        not ended
        and not other
        and current.stripe_subscription_event_at == created
        and current.subscription_status in ENDED_STATUSES
    ):
        # Same-second tie: an ended state is final, a late non-ended event is older.
        return None
    if (
        event_type == CREATED_EVENT
        and not other
        and current.stripe_subscription_event_at == created
    ):
        # Stripe times have one second resolution: a `created` delivered after an
        # `updated` from the same second is the older state.
        return None
    if ended:
        tier, price_id = PlanKey.FREE.value, None
    else:
        tier, price_id = _tier_for(data, current, prices), data.price_id
    return BillingChange(
        stripe_subscription_id=data.subscription_id,
        stripe_price_id=price_id,
        stripe_current_period_end=data.period_end,
        stripe_subscription_event_at=created,
        subscription_tier=tier,
        subscription_status="canceled" if deleted else data.status,
    )


class StripeWebhookService:
    def __init__(
        self,
        events: EventRepository,
        organizations: OrganizationRepository,
        session: AsyncSession,
        prices: Mapping[str, PlanKey],
    ) -> None:
        self.events, self.organizations = events, organizations
        self.session, self.prices = session, prices

    async def handle(self, event: Mapping[str, Any]) -> WebhookOutcome:
        """Apply one verified event; raises MalformedEvent or the handler's own error."""
        event_id = _text(event.get("id"))
        event_type = _text(event.get("type"))
        created = _timestamp(event.get("created"))
        if event_id is None or event_type is None or created is None:
            raise MalformedEvent
        if event_type not in SUBSCRIPTION_EVENTS:
            return WebhookOutcome.IGNORED
        payload = event.get("data")
        subscription = payload.get("object") if isinstance(payload, Mapping) else None
        if not isinstance(subscription, Mapping):
            raise MalformedEvent
        data = parse_subscription(subscription)
        try:
            outcome = await self._apply(event_id, event_type, created, data)
            if outcome is WebhookOutcome.UNMATCHED:
                # Not recorded: the same event is processed if it is redelivered
                # after the organisation is linked to the Stripe customer.
                await self.session.rollback()
            else:
                await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise
        return outcome

    async def _apply(
        self, event_id: str, event_type: str, created: datetime, data: SubscriptionData
    ) -> WebhookOutcome:
        if not await self.events.claim(event_id, event_type, created):
            logger.info("stripe event already processed", extra={"event_id": event_id})
            return WebhookOutcome.DUPLICATE
        current = await self.organizations.get_for_update(
            subscription_id=data.subscription_id, customer_id=data.customer_id
        )
        if current is None:
            logger.warning(
                "stripe subscription matches no organisation",
                extra={"event_id": event_id},
            )
            return WebhookOutcome.UNMATCHED
        change = plan_change(event_type, created, data, current, self.prices)
        if change is None:
            logger.info(
                "stripe event not applied: stale or superseded",
                extra={"event_id": event_id},
            )
            return WebhookOutcome.PROCESSED
        await self.organizations.apply(current.organization_id, change)
        return WebhookOutcome.PROCESSED
