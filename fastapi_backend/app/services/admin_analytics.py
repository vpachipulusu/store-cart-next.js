"""Platform admin analytics (KAN-119): overview, subscription revenue and system stats.

Everything is derived from the platform database. Revenue is the monthly recurring
revenue of billed organisations (``active`` and ``past_due``; a trial pays nothing yet),
priced from the Stripe price catalogue: at most one read per configured price id, never
one per customer. A billed organisation whose price id is unknown or unreadable is
counted as ``unpriced`` and the report says it is incomplete, rather than guessing.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.core.plans import PlanKey
from app.core.stripe_billing import StripeError
from app.core.stripe_prices import StripePriceReader
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
        prices: StripePriceReader | None,
        catalogue: Mapping[str, PriceEntry],
        currency: CurrencySource,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store, self.prices, self.catalogue = store, prices, catalogue
        self.currency, self.clock = currency, clock

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
        amounts = await self._amounts({g.price_id for g in groups if g.price_id})
        monthly: dict[PlanKey, int] = {}
        yearly: dict[PlanKey, int] = {}
        counts: dict[PlanKey, int] = {}
        unpriced = 0
        for group in groups:
            entry = self.catalogue.get(group.price_id or "")
            amount = amounts.get(group.price_id or "")
            if entry is None or amount is None:
                unpriced += group.count
                continue
            counts[entry.plan] = counts.get(entry.plan, 0) + group.count
            target = monthly if entry.interval == "month" else yearly
            target[entry.plan] = target.get(entry.plan, 0) + amount * group.count
        by_plan = [
            PlanRevenue(
                plan,
                counts[plan],
                monthly.get(plan, 0) + round(yearly.get(plan, 0) / MONTHS_PER_YEAR),
            )
            for plan in (PlanKey.PRO, PlanKey.ENTERPRISE)
            if plan in counts
        ]
        mrr = sum(item.mrr_minor for item in by_plan)
        return RevenueReport(
            currency=await self.currency.currency(),
            mrr_minor=mrr,
            arr_minor=mrr * MONTHS_PER_YEAR,
            billed_organizations=sum(g.count for g in groups),
            unpriced_organizations=unpriced,
            by_plan=by_plan,
            breakdown=breakdown,
        )

    async def _amounts(self, price_ids: set[str]) -> dict[str, int]:
        """Unit amounts (minor units) for the price ids the catalogue knows."""
        found: dict[str, int] = {}
        if self.prices is None:
            return found
        for price_id in sorted(price_ids & self.catalogue.keys()):
            try:
                amount = await self.prices.get_unit_amount(price_id)
            except StripeError:
                continue
            if amount is not None:
                found[price_id] = amount
        return found
