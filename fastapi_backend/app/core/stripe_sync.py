"""Stripe bulk subscription listing for reconciliation (KAN-119).

One paginated ``GET /subscriptions`` call per hundred subscriptions, instead of one call
per customer. Same rules as ``stripe_billing``: no Stripe text reaches a log or a
response; only the fields reconciliation compares are kept.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings
from app.core.stripe_billing import HttpStripeBilling, as_text

PAGE_SIZE = 100
MAX_STATUS_LENGTH = 32


@dataclass(frozen=True)
class StripeSubscriptionSnapshot:
    id: str
    customer_id: str | None
    status: str
    price_id: str | None
    cancel_at_period_end: bool


@dataclass(frozen=True)
class StripeSubscriptionPage:
    items: list[StripeSubscriptionSnapshot]
    # Id of the last row Stripe sent (even one that was skipped): the next page's cursor.
    cursor: str | None
    has_more: bool


class StripeSubscriptionLister(Protocol):
    async def list_subscriptions(
        self, starting_after: str | None
    ) -> StripeSubscriptionPage: ...


def _id_of(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("id")
    return as_text(value)


def _snapshot(row: dict[str, Any]) -> StripeSubscriptionSnapshot | None:
    subscription_id, status = as_text(row.get("id")), as_text(row.get("status"))
    if subscription_id is None or status is None:
        return None
    items = row.get("items")
    data = items.get("data") if isinstance(items, dict) else None
    first = data[0] if isinstance(data, list) and data else None
    price = first.get("price") if isinstance(first, dict) else None
    return StripeSubscriptionSnapshot(
        id=subscription_id,
        customer_id=_id_of(row.get("customer")),
        status=status[:MAX_STATUS_LENGTH],
        price_id=_id_of(price),
        # A cancellation scheduled for a date ends the subscription like the flag does.
        cancel_at_period_end=row.get("cancel_at_period_end") is True
        or isinstance(row.get("cancel_at"), int),
    )


class HttpStripeSubscriptionLister(HttpStripeBilling):
    async def list_subscriptions(
        self, starting_after: str | None
    ) -> StripeSubscriptionPage:
        params = {"status": "all", "limit": str(PAGE_SIZE)}
        if starting_after:
            params["starting_after"] = starting_after
        body = await self._call("GET", "/subscriptions", params=params)
        items: list[StripeSubscriptionSnapshot] = []
        cursor: str | None = None
        for row in body.get("data") or []:
            if not isinstance(row, dict):
                continue
            cursor = as_text(row.get("id")) or cursor
            snapshot = _snapshot(row)  # one unusable row never hides the others
            if snapshot is not None:
                items.append(snapshot)
        return StripeSubscriptionPage(
            items, cursor, has_more=body.get("has_more") is True and cursor is not None
        )


def get_stripe_subscription_lister() -> StripeSubscriptionLister | None:
    """The one place the real client is built; None when Stripe is not configured."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        return None
    return HttpStripeSubscriptionLister(secret.get_secret_value())
