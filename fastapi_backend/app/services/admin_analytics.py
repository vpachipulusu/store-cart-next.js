"""Platform admin analytics (KAN-119): overview, subscription revenue and system stats.

Everything is derived from the platform database. Revenue is the monthly recurring
revenue of billed organisations (``active`` and ``past_due``; a trial pays nothing yet),
priced at the Stripe list price (quantity, coupons and tax are not modelled): at most one read per configured price id, never
one per customer. A billed organisation whose price id is unknown or unreadable is
counted as ``unpriced`` and the report says it is incomplete, rather than guessing.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.core.plans import PlanKey
from app.core.stripe_billing import StripeError
from app.core.stripe_prices import StripePrice, StripePriceDetailsReader
from app.repositories.admin_analytics import (
    OverviewCounts,
    PriceGroup,
    SubscriptionBreakdown,
    SystemCounts,
)

REVENUE_STATUSES = frozenset({"active", "past_due"})
ACTIVE_WINDOW_DAYS = 30
MONTHS_PER_YEAR = 12

Interval = Literal["month", "year"]


@dataclass(frozen=True)
class PriceEntry:
    plan: PlanKey
    interval: Interval


@dataclass(frozen=True)
class PlanRevenue:
    plan: PlanKey
    organizations: int
    mrr_minor: int


@dataclass(frozen=True)
class RevenueReport:
    currency: str
    mrr_minor: int
    arr_minor: int
    billed_organizations: int
    unpriced_organizations: int
    by_plan: list[PlanRevenue]
    breakdown: SubscriptionBreakdown

    @property
    def complete(self) -> bool:
        return self.unpriced_organizations == 0


class AnalyticsStore(Protocol):
    async def overview(
        self, since: datetime, active_since: datetime
    ) -> OverviewCounts: ...
    async def billed_price_groups(
        self, statuses: frozenset[str]
    ) -> list[PriceGroup]: ...
    async def subscription_breakdown(self, now: datetime) -> SubscriptionBreakdown: ...
    async def system_counts(self) -> SystemCounts: ...


class CurrencySource(Protocol):
    async def currency(self) -> str: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AdminAnalyticsService:
    def __init__(
        self,
        store: AnalyticsStore,
        prices: StripePriceDetailsReader | None,
        catalogue: Mapping[str, PriceEntry],
        currency: CurrencySource,
        release: Callable[[], Awaitable[None]],
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store, self.prices, self.catalogue = store, prices, catalogue
        self.currency, self.release, self.clock = currency, release, clock

    async def overview(self) -> OverviewCounts:
        now = self.clock()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return await self.store.overview(
            month_start, now - timedelta(days=ACTIVE_WINDOW_DAYS)
        )

    async def system(self) -> SystemCounts:
        return await self.store.system_counts()

    async def revenue(self) -> RevenueReport:
        groups = await self.store.billed_price_groups(REVENUE_STATUSES)
        breakdown = await self.store.subscription_breakdown(self.clock())
        currency = await self.currency.currency()
        # End the read transaction: no connection is held while Stripe is called.
        await self.release()
        found = await self._prices({g.price_id for g in groups if g.price_id})
        monthly: dict[PlanKey, int] = {}
        yearly: dict[PlanKey, int] = {}
        counts: dict[PlanKey, int] = {}
        unpriced = 0
        for group in groups:
            entry = self.catalogue.get(group.price_id or "")
            price = found.get(group.price_id or "")
            # A price in another currency than the platform's cannot be added to the total.
            if (
                entry is None
                or price is None
                or price.currency.upper() != currency.upper()
            ):
                unpriced += group.count
                continue
            counts[entry.plan] = counts.get(entry.plan, 0) + group.count
            target = monthly if entry.interval == "month" else yearly
            target[entry.plan] = (
                target.get(entry.plan, 0) + price.unit_amount * group.count
            )
        by_plan = [
            PlanRevenue(
                plan,
                counts[plan],
                monthly.get(plan, 0) + round(yearly.get(plan, 0) / MONTHS_PER_YEAR),
            )
            for plan in (PlanKey.PRO, PlanKey.ENTERPRISE)
            if plan in counts
        ]
        return RevenueReport(
            currency=currency,
            mrr_minor=sum(item.mrr_minor for item in by_plan),
            # Exact: a yearly price is paid once a year, not as 12 rounded months.
            arr_minor=sum(monthly.values()) * MONTHS_PER_YEAR + sum(yearly.values()),
            billed_organizations=sum(g.count for g in groups),
            unpriced_organizations=unpriced,
            by_plan=by_plan,
            breakdown=breakdown,
        )

    async def _prices(self, price_ids: set[str]) -> dict[str, StripePrice]:
        """Price details for the price ids the catalogue knows."""
        found: dict[str, StripePrice] = {}
        if self.prices is None:
            return found
        for price_id in sorted(price_ids & self.catalogue.keys()):
            try:
                price = await self.prices.get_price(price_id)
            except StripeError:
                continue
            if price is not None:
                found[price_id] = price
        return found
