"""Merchant analytics route against real store databases (KAN-96).

Seeds orders across statuses, currencies, refunds and day boundaries straight into the store
databases (the analytics are read-only, so how an order got its status does not matter), then
checks exact numbers, bucketing, range limits, roles and that another store's orders are never
counted. Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server (see
``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.ids import new_id
from app.repositories.store_analytics import SALES_BY_BUCKET_SQL, TOP_PRODUCTS_SQL
from app.services.store_analytics import SALES_STATUSES
from app.services.store_sessions import open_store_session
from tests.api.products_support import (  # noqa: F401  (fixtures)
    as_user,
    assert_no_database_text,
    client,
    error_of,
    store_of,
    world,
)
from tests.isolation_world import World, same_failure
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

ALICE = as_user("alice")  # OWNER of A
DANA = as_user("dana")  # ADMIN of A
AMY = as_user("amy")  # STAFF of A
BOB = as_user("bob")  # OWNER of B
EVE = as_user("eve")  # no organisation
OCTOBER = {"from": "2026-10-01", "to": "2026-10-03"}


@dataclass(frozen=True)
class Line:
    product: str
    unit_price_minor: int
    quantity: int
    variant_label: str | None = None


@dataclass(frozen=True)
class Refund:
    amount_minor: int
    status: str = "succeeded"


def at(text_value: str) -> datetime:
    return datetime.fromisoformat(text_value).replace(tzinfo=UTC)


async def seed_order(
    world: World,
    store_id: str,
    *,
    status: str,
    created_at: datetime,
    lines: list[Line],
    currency: str = "GBP",
    tax_minor: int = 0,
    refunds: tuple[Refund, ...] = (),
) -> str:
    order_id = new_id()
    subtotal = sum(line.unit_price_minor * line.quantity for line in lines)
    async with open_store_session(store_id, world.provider) as session:
        await session.execute(
            text(
                "INSERT INTO orders (id, status, currency, subtotal_minor, tax_minor,"
                " total_minor, tracking_number, created_at, updated_at)"
                " VALUES (:id, :status, :currency, :subtotal, :tax, :total,"
                " :tracking, :created, :created)"
            ),
            {
                "id": order_id,
                "status": status,
                "currency": currency,
                "subtotal": subtotal,
                "tax": tax_minor,
                "total": subtotal + tax_minor,
                "tracking": "TRK-1" if status in ("fulfilled", "refunded") else None,
                "created": created_at,
            },
        )
        for line in lines:
            await session.execute(
                text(
                    "INSERT INTO order_items (id, order_id, product_name, sku,"
                    " variant_label, unit_price_minor, quantity, tax_rate_bps,"
                    " tax_minor) VALUES (:id, :order_id, :name, :sku, :label,"
                    " :price, :quantity, 0, 0)"
                ),
                {
                    "id": new_id(),
                    "order_id": order_id,
                    "name": line.product,
                    "sku": f"SKU-{new_id()[:8]}",
                    "label": line.variant_label,
                    "price": line.unit_price_minor,
                    "quantity": line.quantity,
                },
            )
        for refund in refunds:
            await session.execute(
                text(
                    "INSERT INTO order_refunds (id, order_id, amount_minor, currency,"
                    " status) VALUES (:id, :order_id, :amount, :currency, :status)"
                ),
                {
                    "id": new_id(),
                    "order_id": order_id,
                    "amount": refund.amount_minor,
                    "currency": currency,
                    "status": refund.status,
                },
            )
        await session.commit()
    return order_id


def main_store(world: World) -> str:
    return store_of(world, "a", "south")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded(world: World) -> World:
    """Orders in ``a.south`` (the store under test) and noise in two other stores."""
    store = main_store(world)
    mug, lamp = "Mug", "Lamp"
    # 1 October: a taxed paid order, and a fulfilled one with one refund of each status.
    await seed_order(
        world,
        store,
        status="paid",
        created_at=at("2026-10-01T00:00:00"),
        lines=[Line(mug, 1000, 4)],
        tax_minor=800,
    )
    await seed_order(
        world,
        store,
        status="fulfilled",
        created_at=at("2026-10-01T23:59:59.999999"),
        lines=[Line(lamp, 5000, 1, "Large")],
        refunds=(Refund(1000), Refund(500, "pending"), Refund(300, "failed")),
    )
    # 2 October: a paid order in GBP and one in USD; pending and cancelled are not sales.
    await seed_order(
        world,
        store,
        status="paid",
        created_at=at("2026-10-02T12:00:00"),
        lines=[Line(lamp, 3000, 2, "Small")],
    )
    await seed_order(
        world,
        store,
        status="paid",
        currency="USD",
        created_at=at("2026-10-02T12:00:00"),
        lines=[Line("Pen", 200, 3)],
    )
    for status in ("pending", "cancelled"):
        await seed_order(
            world,
            store,
            status=status,
            created_at=at("2026-10-02T13:00:00"),
            lines=[Line(mug, 1000, 50)],
        )
    # 3 October: an order refunded in full.
    await seed_order(
        world,
        store,
        status="refunded",
        created_at=at("2026-10-03T00:00:00"),
        lines=[Line(mug, 1000, 1)],
        refunds=(Refund(1000),),
    )
    # Just outside the range on both sides.
    for created in ("2026-09-30T23:59:59.999999", "2026-10-04T00:00:00"):
        await seed_order(
            world,
            store,
            status="paid",
            created_at=at(created),
            lines=[Line(mug, 1000, 7)],
        )
    # Another store of the same organisation, and a store of another organisation.
    for label, slug in (("a", "north"), ("b", "north")):
        await seed_order(
            world,
            store_of(world, label, slug),
            status="paid",
            created_at=at("2026-10-01T09:00:00"),
            lines=[Line("Foreign", 999, 1)],
        )
    return world


async def analytics(
    client: AsyncClient,
    store_id: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] = ALICE,
) -> Any:
    return await client.get(
        f"/v1/stores/{store_id}/analytics",
        params=params if params is not None else OCTOBER,
        headers=headers,
    )


def by_currency(body: Any) -> dict[str, Any]:
    return {entry["currency"]: entry for entry in body["data"]["currencies"]}


def point(day: str, orders: int, gross: int, refunds: int, net: int) -> dict[str, Any]:
    return {
        "bucket_start": day,
        "orders": orders,
        "gross_sales_minor": gross,
        "refunds_minor": refunds,
        "net_sales_minor": net,
    }


# --- numbers -------------------------------------------------------------------------


async def test_daily_sales_are_net_of_succeeded_refunds_per_currency(
    client: AsyncClient, seeded: World
) -> None:
    response = await analytics(client, main_store(seeded))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert (
        body["data"]["start_date"],
        body["data"]["end_date"],
        body["data"]["bucket"],
    ) == ("2026-10-01", "2026-10-03", "day")
    currencies = by_currency(body)
    assert list(currencies) == ["GBP", "USD"]
    gbp, usd = currencies["GBP"], currencies["USD"]
    assert gbp["series"] == [
        point("2026-10-01", 2, 4800 + 5000, 1000, 8800),
        point("2026-10-02", 1, 6000, 0, 6000),
        point("2026-10-03", 1, 1000, 1000, 0),
    ]
    assert gbp["totals"] == {
        "orders": 4,
        "gross_sales_minor": 16800,
        "refunds_minor": 2000,
        "net_sales_minor": 14800,
    }
    assert usd["series"] == [
        point("2026-10-01", 0, 0, 0, 0),
        point("2026-10-02", 1, 600, 0, 600),
        point("2026-10-03", 0, 0, 0, 0),
    ]


async def test_top_products_use_the_names_on_the_order_lines(
    client: AsyncClient, seeded: World
) -> None:
    response = await analytics(client, main_store(seeded))

    gbp = by_currency(response.json())["GBP"]
    # Lamp's two variants are one product; line revenue is before tax.
    assert gbp["top_products_by_revenue"] == [
        {"product_name": "Lamp", "units": 3, "revenue_minor": 11000},
        {"product_name": "Mug", "units": 5, "revenue_minor": 5000},
    ]
    assert gbp["top_products_by_units"] == [
        {"product_name": "Mug", "units": 5, "revenue_minor": 5000},
        {"product_name": "Lamp", "units": 3, "revenue_minor": 11000},
    ]
    usd = by_currency(response.json())["USD"]
    assert usd["top_products_by_units"] == [
        {"product_name": "Pen", "units": 3, "revenue_minor": 600}
    ]


async def test_weekly_and_monthly_buckets_are_utc_week_and_month_starts(
    client: AsyncClient, seeded: World
) -> None:
    weekly = await analytics(client, main_store(seeded), {**OCTOBER, "bucket": "week"})
    monthly = await analytics(
        client,
        main_store(seeded),
        {"from": "2026-09-15", "to": "2026-10-03", "bucket": "month"},
    )

    assert by_currency(weekly.json())["GBP"]["series"] == [
        point("2026-09-28", 4, 16800, 2000, 14800)
    ]
    assert by_currency(monthly.json())["GBP"]["series"] == [
        point("2026-09-01", 1, 7000, 0, 7000),
        point("2026-10-01", 4, 16800, 2000, 14800),
    ]


async def test_a_single_day_counts_its_last_microsecond_and_not_the_next_day(
    client: AsyncClient, seeded: World
) -> None:
    first = await analytics(
        client, main_store(seeded), {"from": "2026-10-01", "to": "2026-10-01"}
    )

    assert by_currency(first.json())["GBP"]["totals"]["orders"] == 2
    assert "USD" not in by_currency(first.json())


async def test_a_range_without_sales_is_empty(
    client: AsyncClient, seeded: World
) -> None:
    response = await analytics(
        client, main_store(seeded), {"from": "2020-01-01", "to": "2020-01-31"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["currencies"] == []


async def test_the_default_range_is_the_last_30_utc_days(
    client: AsyncClient, seeded: World
) -> None:
    response = await analytics(client, main_store(seeded), params={})

    data = response.json()["data"]
    end = date.fromisoformat(data["end_date"])
    assert end == datetime.now(UTC).date()
    assert date.fromisoformat(data["start_date"]) == end - timedelta(days=29)
    assert data["bucket"] == "day"


async def test_only_the_top_ten_products_are_returned(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "b", "east")
    await seed_order(
        world,
        store,
        status="paid",
        created_at=at("2026-10-01T10:00:00"),
        lines=[Line(f"P{n:02d}", 100 * n, 13 - n) for n in range(1, 13)],
    )

    response = await analytics(client, store, headers=BOB)

    gbp = by_currency(response.json())["GBP"]
    by_revenue = [p["product_name"] for p in gbp["top_products_by_revenue"]]
    by_units = [p["product_name"] for p in gbp["top_products_by_units"]]
    # Revenue is 100n(13-n), so pairs tie (P06 and P07 at 4200): more units ranks first.
    assert by_revenue == [
        "P06",
        "P07",
        "P05",
        "P08",
        "P04",
        "P09",
        "P03",
        "P10",
        "P02",
        "P11",
    ]
    assert by_units == [f"P{n:02d}" for n in range(1, 11)]


# --- isolation and roles -------------------------------------------------------------


async def test_another_store_only_sees_its_own_orders(
    client: AsyncClient, seeded: World
) -> None:
    sibling = await analytics(client, store_of(seeded, "a", "north"))

    assert by_currency(sibling.json())["GBP"]["totals"] == {
        "orders": 1,
        "gross_sales_minor": 999,
        "refunds_minor": 0,
        "net_sales_minor": 999,
    }


async def test_an_admin_may_read_the_analytics(
    client: AsyncClient, seeded: World
) -> None:
    response = await analytics(client, main_store(seeded), headers=DANA)

    assert response.status_code == 200
    assert by_currency(response.json())["GBP"]["totals"]["orders"] == 4


async def test_staff_are_refused(client: AsyncClient, seeded: World) -> None:
    response = await analytics(client, main_store(seeded), headers=AMY)

    assert response.status_code == 403
    assert error_of(response) == "Forbidden"


async def test_a_foreign_store_is_the_same_404_as_an_unknown_one(
    client: AsyncClient, seeded: World
) -> None:
    unknown = await analytics(client, new_id(), headers=EVE)

    for headers in (EVE, BOB):
        response = await analytics(client, main_store(seeded), headers=headers)
        assert response.status_code == 404
        same_failure(response, unknown)


async def test_a_store_without_a_database_is_a_503(
    client: AsyncClient, world: World
) -> None:
    response = await analytics(client, store_of(world, "a", "east"))

    assert response.status_code == 503
    assert_no_database_text(response)


# --- validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"from": "2026-10-02", "to": "2026-10-01"}, "on or before"),
        ({"from": "2025-01-01", "to": "2026-10-01"}, "366 days"),
    ],
)
async def test_an_invalid_range_is_a_422_with_a_reason(
    client: AsyncClient, seeded: World, params: dict[str, str], message: str
) -> None:
    response = await analytics(client, main_store(seeded), params)

    assert response.status_code == 422
    assert message in error_of(response)


@pytest.mark.parametrize(
    "params",
    [{"bucket": "year"}, {"from": "yesterday"}, {"to": "2026-13-01"}],
)
async def test_malformed_parameters_are_rejected(
    client: AsyncClient, seeded: World, params: dict[str, str]
) -> None:
    response = await analytics(client, main_store(seeded), params)

    assert response.status_code == 422


# --- query plans ---------------------------------------------------------------------


@pytest.mark.parametrize("sql", [SALES_BY_BUCKET_SQL, TOP_PRODUCTS_SQL])
async def test_the_queries_read_orders_through_an_existing_index(
    seeded: World, sql: Any
) -> None:
    params = {
        "since": at("2026-10-01T00:00:00"),
        "until": at("2026-10-04T00:00:00"),
        "bucket": "day",
        "statuses": list(SALES_STATUSES),
        "limit": 10,
    }
    async with open_store_session(main_store(seeded), seeded.provider) as session:
        # The tables are tiny, so the planner prefers a scan; forbid it to see the index fit.
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            (await session.execute(text(f"EXPLAIN {sql.text}"), params)).scalars()
        )

    # Either orders index fits: (status, created_at) from 0004 or (created_at, id) from 0005.
    assert re.search(
        r"Index (Only )?Scan using ix_orders_(status_)?created_at on orders", plan
    ), plan
    assert "Seq Scan on orders" not in plan
