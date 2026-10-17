"""Test doubles for the admin analytics and Stripe sync tests (KAN-119)."""

from app.core.stripe_billing import StripeError
from app.core.stripe_prices import StripePrice
from app.core.stripe_sync import (
    PAGE_SIZE,
    StripeSubscriptionPage,
    StripeSubscriptionSnapshot,
)


def snapshot(
    sub_id: str = "sub_1",
    customer: str | None = "cus_1",
    status: str = "active",
    price: str | None = "price_pro_m",
    cancel: bool = False,
) -> StripeSubscriptionSnapshot:
    return StripeSubscriptionSnapshot(sub_id, customer, status, price, cancel)


class FakeLister:
    """Serves the given snapshots in pages of ``page_size``, like Stripe's cursor API."""

    def __init__(
        self, items: list[StripeSubscriptionSnapshot], page_size: int = PAGE_SIZE
    ) -> None:
        self.items, self.page_size = items, page_size
        self.fail = False
        self.fail_on_call: int | None = None
        self.skipped = 0
        self.cursors: list[str | None] = []

    async def list_subscriptions(
        self, starting_after: str | None
    ) -> StripeSubscriptionPage:
        self.cursors.append(starting_after)
        if self.fail or self.fail_on_call == len(self.cursors):
            raise StripeError("Stripe request failed")
        start = 0
        if starting_after is not None:
            start = [s.id for s in self.items].index(starting_after) + 1
        chunk = self.items[start : start + self.page_size]
        more = start + self.page_size < len(self.items)
        return StripeSubscriptionPage(
            chunk, chunk[-1].id if chunk else None, more, self.skipped
        )


class FakePrices:
    """A price reader with fixed amounts; unknown ids raise like an unreadable price."""

    def __init__(self, amounts: dict[str, int | None], currency: str = "GBP") -> None:
        self.amounts, self.currency = amounts, currency
        self.currencies: dict[str, str] = {}
        self.calls: list[str] = []

    async def get_price(self, price_id: str) -> StripePrice | None:
        self.calls.append(price_id)
        if price_id not in self.amounts:
            raise StripeError("Stripe request failed")
        amount = self.amounts[price_id]
        if amount is None:
            return None
        return StripePrice(amount, self.currencies.get(price_id, self.currency))
