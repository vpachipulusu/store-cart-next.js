"""Merchant sales analytics for one store (KAN-96). No FastAPI imports.

Definitions (also in ``docs/developer/merchant-analytics.md``):

* A **sale** is an order in ``paid``, ``fulfilled`` or ``refunded`` status: every status an
  order only reaches once the shopper has paid. ``pending`` (unpaid) and ``cancelled`` orders
  are never counted.
* **Gross sales** is the order total (lines, shipping and any tax added at checkout);
  **refunds** are the order's ``succeeded`` refunds; **net sales** is gross minus refunds. A
  refund counts in the bucket of its order, so a bucket's net sales never goes below zero.
* Orders are placed in buckets by ``created_at`` (placed at checkout) in UTC, not ``paid_at``, which only
  the payment webhook sets and no index covers: calendar days, ISO weeks starting on Monday, or calendar
  months. Empty buckets are filled with zeros so a series is continuous. The first and last week or month
  bucket can cover only part of the range.
* Money is integer minor units, grouped by the order's own currency and never converted.
* Top products are ranked per currency by line revenue (unit price times quantity, as saved
  on the order) and by units, over the same sales.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Protocol

from app.repositories.store_analytics import BucketSalesRow, ProductSalesRow
from app.services.store_orders import OrderStatus

SALES_STATUSES: tuple[str, ...] = (
    OrderStatus.PAID.value,
    OrderStatus.FULFILLED.value,
    OrderStatus.REFUNDED.value,
)
DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 366  # inclusive: a whole year, leap years too
TOP_PRODUCTS_LIMIT = 10
# Bounds keep the date arithmetic (defaults, the exclusive end, month steps) far from date.min/max.
EARLIEST_DATE = date(2000, 1, 1)
LATEST_DATE = date(2099, 12, 31)


class Bucket(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class InvalidAnalyticsRange(Exception):
    """The requested range is not acceptable (message is safe to show)."""


@dataclass(frozen=True)
class AnalyticsRange:
    start: date
    end: date  # inclusive
    bucket: Bucket

    @property
    def since(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=UTC)

    @property
    def until(self) -> datetime:
        """Exclusive: midnight UTC after ``end``."""
        return datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=UTC)


@dataclass(frozen=True)
class SalesPoint:
    start: date
    orders: int
    gross_minor: int
    refunds_minor: int

    @property
    def net_minor(self) -> int:
        return self.gross_minor - self.refunds_minor


@dataclass(frozen=True)
class ProductSales:
    product_name: str
    units: int
    revenue_minor: int


@dataclass(frozen=True)
class CurrencyAnalytics:
    currency: str
    totals: SalesPoint  # ``start`` is the range start
    series: tuple[SalesPoint, ...]
    top_by_revenue: tuple[ProductSales, ...]
    top_by_units: tuple[ProductSales, ...]


@dataclass(frozen=True)
class AnalyticsReport:
    start: date
    end: date
    bucket: Bucket
    currencies: list[CurrencyAnalytics]


class AnalyticsStore(Protocol):
    async def sales_by_bucket(
        self,
        *,
        since: datetime,
        until: datetime,
        bucket: str,
        statuses: Sequence[str],
    ) -> list[BucketSalesRow]: ...

    async def top_products(
        self,
        *,
        since: datetime,
        until: datetime,
        statuses: Sequence[str],
        limit: int,
    ) -> list[ProductSalesRow]: ...


def _utc_today() -> date:
    return datetime.now(UTC).date()


def resolve_range(
    start: date | None, end: date | None, bucket: Bucket, today: date
) -> AnalyticsRange:
    """Fill in the defaults (the 30 days up to today, or up to ``end``) and check the range."""
    for given in (start, end):
        if given is not None and not EARLIEST_DATE <= given <= LATEST_DATE:
            raise InvalidAnalyticsRange(
                f"Dates must be between {EARLIEST_DATE.isoformat()}"
                f" and {LATEST_DATE.isoformat()}"
            )
    if end is None:
        if start is not None and start > today:
            raise InvalidAnalyticsRange("The start date must not be after today")
        end = today
    if start is None:
        start = end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise InvalidAnalyticsRange("The start date must be on or before the end date")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise InvalidAnalyticsRange(
            f"The range can cover at most {MAX_RANGE_DAYS} days"
        )
    return AnalyticsRange(start, end, bucket)


def bucket_start(day: date, bucket: Bucket) -> date:
    """The bucket ``day`` falls in, as Postgres ``date_trunc`` names it."""
    if bucket is Bucket.WEEK:
        return day - timedelta(days=day.weekday())
    if bucket is Bucket.MONTH:
        return day.replace(day=1)
    return day


def _next_bucket(start: date, bucket: Bucket) -> date:
    if bucket is Bucket.DAY:
        return start + timedelta(days=1)
    if bucket is Bucket.WEEK:
        return start + timedelta(weeks=1)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def bucket_starts(analytics_range: AnalyticsRange) -> list[date]:
    """Every bucket the range touches, oldest first."""
    starts: list[date] = []
    current = bucket_start(analytics_range.start, analytics_range.bucket)
    while current <= analytics_range.end:
        starts.append(current)
        current = _next_bucket(current, analytics_range.bucket)
    return starts


def _products(
    rows: list[ProductSalesRow], rank: Callable[[ProductSalesRow], int]
) -> tuple[ProductSales, ...]:
    ranked = sorted((row for row in rows if rank(row) <= TOP_PRODUCTS_LIMIT), key=rank)
    return tuple(
        ProductSales(row.product_name, row.units, row.revenue_minor) for row in ranked
    )


def _currency(
    currency: str,
    starts: list[date],
    sales: list[BucketSalesRow],
    products: list[ProductSalesRow],
    range_start: date,
) -> CurrencyAnalytics:
    found = {row.bucket_start: row for row in sales}
    series = tuple(
        SalesPoint(
            start,
            found[start].orders,
            found[start].gross_minor,
            found[start].refunds_minor,
        )
        if start in found
        else SalesPoint(start, 0, 0, 0)
        for start in starts
    )
    totals = SalesPoint(
        range_start,
        sum(p.orders for p in series),
        sum(p.gross_minor for p in series),
        sum(p.refunds_minor for p in series),
    )
    return CurrencyAnalytics(
        currency,
        totals,
        series,
        _products(products, lambda row: row.revenue_rank),
        _products(products, lambda row: row.units_rank),
    )


class StoreAnalyticsService:
    def __init__(
        self, store: AnalyticsStore, today: Callable[[], date] = _utc_today
    ) -> None:
        self.store, self.today = store, today

    async def report(
        self, *, start: date | None, end: date | None, bucket: Bucket
    ) -> AnalyticsReport:
        """Sales, orders and top products of the store over the range, per currency."""
        resolved = resolve_range(start, end, bucket, self.today())
        sales = await self.store.sales_by_bucket(
            since=resolved.since,
            until=resolved.until,
            bucket=resolved.bucket.value,
            statuses=SALES_STATUSES,
        )
        products = await self.store.top_products(
            since=resolved.since,
            until=resolved.until,
            statuses=SALES_STATUSES,
            limit=TOP_PRODUCTS_LIMIT,
        )
        starts = bucket_starts(resolved)
        currencies = sorted(
            {row.currency for row in sales} | {row.currency for row in products}
        )
        return AnalyticsReport(
            resolved.start,
            resolved.end,
            resolved.bucket,
            [
                _currency(
                    currency,
                    starts,
                    [row for row in sales if row.currency == currency],
                    [row for row in products if row.currency == currency],
                    resolved.start,
                )
                for currency in currencies
            ],
        )
