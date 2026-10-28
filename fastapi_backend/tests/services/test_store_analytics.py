"""Merchant analytics service (KAN-96): range rules, bucket filling, totals and top products.

The store is a local fake behind the ``AnalyticsStore`` protocol; the SQL itself is proven
against real Postgres in ``tests/api/test_store_analytics_e2e.py``.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from app.repositories.store_analytics import BucketSalesRow, ProductSalesRow
from app.services.store_analytics import (
    DEFAULT_RANGE_DAYS,
    MAX_RANGE_DAYS,
    SALES_STATUSES,
    Bucket,
    InvalidAnalyticsRange,
    StoreAnalyticsService,
    bucket_start,
    bucket_starts,
    resolve_range,
)

TODAY = date(2026, 10, 28)  # a Wednesday


class FakeAnalyticsStore:
    def __init__(
        self,
        sales: Sequence[BucketSalesRow] = (),
        products: Sequence[ProductSalesRow] = (),
    ) -> None:
        self.sales, self.products = list(sales), list(products)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def sales_by_bucket(
        self,
        *,
        since: datetime,
        until: datetime,
        bucket: str,
        statuses: Sequence[str],
    ) -> list[BucketSalesRow]:
        self.calls.append(
            (
                "sales",
                {
                    "since": since,
                    "until": until,
                    "bucket": bucket,
                    "statuses": statuses,
                },
            )
        )
        return self.sales

    async def top_products(
        self,
        *,
        since: datetime,
        until: datetime,
        statuses: Sequence[str],
        limit: int,
    ) -> list[ProductSalesRow]:
        self.calls.append(
            (
                "products",
                {"since": since, "until": until, "statuses": statuses, "limit": limit},
            )
        )
        return self.products


def service(store: FakeAnalyticsStore) -> StoreAnalyticsService:
    return StoreAnalyticsService(store, today=lambda: TODAY)


# --- range rules ---------------------------------------------------------------------


def test_the_default_range_is_the_last_30_days_including_today() -> None:
    resolved = resolve_range(None, None, Bucket.DAY, TODAY)

    assert (resolved.start, resolved.end) == (date(2026, 9, 29), TODAY)
    assert (resolved.end - resolved.start).days + 1 == DEFAULT_RANGE_DAYS


def test_only_a_start_runs_to_today() -> None:
    resolved = resolve_range(date(2026, 10, 1), None, Bucket.DAY, TODAY)

    assert (resolved.start, resolved.end) == (date(2026, 10, 1), TODAY)


def test_only_an_end_takes_the_30_days_before_it() -> None:
    resolved = resolve_range(None, date(2026, 3, 30), Bucket.DAY, TODAY)

    assert (resolved.start, resolved.end) == (date(2026, 3, 1), date(2026, 3, 30))


def test_a_single_day_is_a_valid_range() -> None:
    resolved = resolve_range(TODAY, TODAY, Bucket.DAY, TODAY)

    assert resolved.since == datetime(2026, 10, 28, tzinfo=UTC)
    assert resolved.until == datetime(2026, 10, 29, tzinfo=UTC)


def test_a_start_after_the_end_is_refused() -> None:
    with pytest.raises(InvalidAnalyticsRange, match="on or before"):
        resolve_range(date(2026, 10, 2), date(2026, 10, 1), Bucket.DAY, TODAY)


def test_the_longest_range_is_accepted_and_one_more_day_is_refused() -> None:
    end = date(2026, 12, 31)
    longest = resolve_range(date(2025, 12, 31), end, Bucket.DAY, TODAY)
    assert (longest.end - longest.start).days + 1 == MAX_RANGE_DAYS

    with pytest.raises(InvalidAnalyticsRange, match="366 days"):
        resolve_range(date(2025, 12, 30), end, Bucket.DAY, TODAY)


# --- buckets -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "bucket", "expected"),
    [
        (date(2026, 10, 28), Bucket.DAY, date(2026, 10, 28)),
        (date(2026, 10, 28), Bucket.WEEK, date(2026, 10, 26)),  # ISO week, Monday
        (date(2026, 10, 26), Bucket.WEEK, date(2026, 10, 26)),
        (date(2026, 11, 1), Bucket.WEEK, date(2026, 10, 26)),  # Sunday
        (date(2026, 10, 28), Bucket.MONTH, date(2026, 10, 1)),
    ],
)
def test_bucket_start_matches_postgres_date_trunc(
    day: date, bucket: Bucket, expected: date
) -> None:
    assert bucket_start(day, bucket) == expected


def test_weekly_buckets_start_on_the_monday_of_the_first_day() -> None:
    resolved = resolve_range(date(2026, 10, 1), date(2026, 10, 20), Bucket.WEEK, TODAY)

    assert bucket_starts(resolved) == [
        date(2026, 9, 28),
        date(2026, 10, 5),
        date(2026, 10, 12),
        date(2026, 10, 19),
    ]


def test_monthly_buckets_cross_the_year_end() -> None:
    resolved = resolve_range(date(2025, 11, 15), date(2026, 2, 3), Bucket.MONTH, TODAY)

    assert bucket_starts(resolved) == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]


# --- report --------------------------------------------------------------------------


async def test_empty_buckets_are_filled_and_totals_add_up() -> None:
    store = FakeAnalyticsStore(
        sales=[
            BucketSalesRow("GBP", date(2026, 10, 2), 2, 5000, 1000),
            BucketSalesRow("GBP", date(2026, 10, 4), 1, 2500, 0),
        ]
    )

    report = await service(store).report(
        start=date(2026, 10, 1), end=date(2026, 10, 4), bucket=Bucket.DAY
    )

    [gbp] = report.currencies
    assert gbp.currency == "GBP"
    assert [(p.start, p.orders, p.net_minor) for p in gbp.series] == [
        (date(2026, 10, 1), 0, 0),
        (date(2026, 10, 2), 2, 4000),
        (date(2026, 10, 3), 0, 0),
        (date(2026, 10, 4), 1, 2500),
    ]
    totals = gbp.totals
    assert (totals.orders, totals.gross_minor, totals.refunds_minor) == (3, 7500, 1000)
    assert totals.net_minor == 6500


async def test_each_currency_has_its_own_series_and_is_never_converted() -> None:
    store = FakeAnalyticsStore(
        sales=[
            BucketSalesRow("USD", date(2026, 10, 1), 1, 900, 0),
            BucketSalesRow("EUR", date(2026, 10, 2), 1, 700, 100),
        ]
    )

    report = await service(store).report(
        start=date(2026, 10, 1), end=date(2026, 10, 2), bucket=Bucket.DAY
    )

    assert [c.currency for c in report.currencies] == ["EUR", "USD"]
    eur, usd = report.currencies
    assert [p.gross_minor for p in eur.series] == [0, 700]
    assert [p.gross_minor for p in usd.series] == [900, 0]
    assert (eur.totals.net_minor, usd.totals.net_minor) == (600, 900)


async def test_a_currency_with_only_product_rows_still_gets_a_full_series() -> None:
    store = FakeAnalyticsStore(products=[ProductSalesRow("JPY", "Tea", 1, 500, 1, 1)])

    report = await service(store).report(
        start=date(2026, 10, 1), end=date(2026, 10, 2), bucket=Bucket.DAY
    )

    [jpy] = report.currencies
    assert [p.orders for p in jpy.series] == [0, 0]
    assert [p.product_name for p in jpy.top_by_revenue] == ["Tea"]


async def test_no_orders_gives_no_currencies() -> None:
    report = await service(FakeAnalyticsStore()).report(
        start=None, end=None, bucket=Bucket.DAY
    )

    assert report.currencies == []
    assert (report.start, report.end, report.bucket) == (
        date(2026, 9, 29),
        TODAY,
        Bucket.DAY,
    )


async def test_top_products_are_split_by_ranking_and_kept_in_rank_order() -> None:
    store = FakeAnalyticsStore(
        products=[
            ProductSalesRow("GBP", "Mug", 10, 1000, 2, 1),
            ProductSalesRow("GBP", "Lamp", 1, 9000, 1, 11),
            ProductSalesRow("GBP", "Pen", 5, 50, 11, 2),
        ]
    )

    report = await service(store).report(start=TODAY, end=TODAY, bucket=Bucket.DAY)

    [gbp] = report.currencies
    assert [p.product_name for p in gbp.top_by_revenue] == ["Lamp", "Mug"]
    assert [p.product_name for p in gbp.top_by_units] == ["Mug", "Pen"]
    assert (gbp.top_by_units[0].units, gbp.top_by_units[0].revenue_minor) == (
        10,
        1000,
    )


async def test_the_store_is_asked_for_the_utc_range_and_the_sales_statuses() -> None:
    store = FakeAnalyticsStore()

    await service(store).report(
        start=date(2026, 10, 1), end=date(2026, 10, 31), bucket=Bucket.WEEK
    )

    (_, sales), (_, products) = store.calls
    assert sales == {
        "since": datetime(2026, 10, 1, tzinfo=UTC),
        "until": datetime(2026, 11, 1, tzinfo=UTC),
        "bucket": "week",
        "statuses": SALES_STATUSES,
    }
    assert products["limit"] == 10
    assert set(SALES_STATUSES) == {"paid", "fulfilled", "refunded"}


async def test_an_invalid_range_never_reaches_the_store() -> None:
    store = FakeAnalyticsStore()

    with pytest.raises(InvalidAnalyticsRange):
        await service(store).report(
            start=date(2026, 10, 2), end=date(2026, 10, 1), bucket=Bucket.DAY
        )

    assert store.calls == []
