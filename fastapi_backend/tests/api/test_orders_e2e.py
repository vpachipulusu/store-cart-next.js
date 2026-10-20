"""Merchant order routes against real store databases (KAN-79, KAN-195 AC 3).

List, detail and manual fulfilment, plus tenant isolation (a foreign store id, another store's
order id under the caller's own store, a sibling store), roles, store status and the
concurrent double fulfilment. Runs only when ``TEST_DATABASE_URL`` points at a throwaway
local server (see ``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.services.store_orders import (
    OrderLineInput,
    OrderStatus,
    create_order,
    transition_order,
)
from app.services.store_sessions import open_store_session
from tests.api.products_support import (  # noqa: F401  (fixtures)
    as_user,
    assert_no_database_text,
    client,
    create_product,
    error_of,
    simple_payload,
    store_of,
    unique,
    world,
)
from tests.isolation_world import World, internal_key, same_failure
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

ALICE = as_user("alice")
AMY = as_user("amy")
DANA = as_user("dana")
GENERIC_409 = "Only a paid order can be fulfilled"


def orders_url(store_id: str, suffix: str = "") -> str:
    return f"/v1/stores/{store_id}/orders{suffix}"


def north(world: World) -> str:
    return store_of(world, "a", "north")


async def place_order(
    client: AsyncClient,
    world: World,
    store_id: str,
    *,
    owner: str = "alice",
    paid: bool = True,
    quantity: int = 2,
) -> str:
    """An order on ``store_id`` for a fresh active product; ``paid`` moves it to paid."""
    payload = simple_payload(status="active")
    product = await create_product(client, store_id, owner, payload)
    async with open_store_session(store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=2000,
            lines=[
                OrderLineInput(
                    variant_id=product["variants"][0]["id"], quantity=quantity
                )
            ],
        )
        if paid:
            await transition_order(session, order.id, OrderStatus.PAID)
        await session.commit()
    return order.id


async def stored_row(world: World, store_id: str, order_id: str) -> dict[str, Any]:
    async with open_store_session(store_id, world.provider) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status, tracking_number, carrier, fulfilled_at "
                        "FROM orders WHERE id = :i"
                    ),
                    {"i": order_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def fulfil(
    client: AsyncClient,
    store_id: str,
    order_id: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] = ALICE,
) -> Response:
    return await client.post(
        orders_url(store_id, f"/{order_id}/fulfil"),
        json=body if body is not None else {"tracking_number": "TRK-1"},
        headers=headers,
    )


# --- list ----------------------------------------------------------------------------


async def test_list_is_newest_first_with_item_counts_and_paging(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "b", "south")
    first = await place_order(client, world, store, owner="bob", quantity=3)
    second = await place_order(client, world, store, owner="bob", quantity=1)
    third = await place_order(client, world, store, owner="bob", paid=False)

    page = await client.get(orders_url(store), headers=as_user("bob"))

    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    body = page.json()
    assert [o["id"] for o in body["data"][:3]] == [third, second, first]
    assert body["total"] == 3
    assert (body["limit"], body["offset"]) == (25, 0)
    by_id = {o["id"]: o for o in body["data"]}
    assert by_id[first]["item_count"] == 3
    assert by_id[first]["currency"] == "GBP"
    assert by_id[first]["status"] == "paid"
    assert by_id[first]["tracking_number"] is None

    paged = await client.get(
        orders_url(store), params={"limit": 1, "offset": 1}, headers=as_user("bob")
    )
    assert [o["id"] for o in paged.json()["data"]] == [second]
    assert paged.json()["total"] == 3


async def test_list_filters_by_status(client: AsyncClient, world: World) -> None:
    store = store_of(world, "b", "south")

    paid = await client.get(
        orders_url(store), params={"status": "paid"}, headers=as_user("bob")
    )
    pending = await client.get(
        orders_url(store), params={"status": "pending"}, headers=as_user("bob")
    )

    assert paid.json()["total"] == 2
    assert {o["status"] for o in paid.json()["data"]} == {"paid"}
    assert pending.json()["total"] == 1


@pytest.mark.parametrize(
    "params",
    [{"status": "shipped"}, {"limit": 0}, {"limit": 101}, {"offset": -1}],
)
async def test_list_rejects_bad_parameters(
    client: AsyncClient, world: World, params: dict[str, Any]
) -> None:
    response = await client.get(orders_url(north(world)), params=params, headers=ALICE)

    assert response.status_code == 422


# --- detail --------------------------------------------------------------------------


async def test_detail_returns_totals_and_the_purchase_snapshot(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    order_id = await place_order(client, world, store, quantity=2)

    response = await client.get(orders_url(store, f"/{order_id}"), headers=ALICE)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == order_id
    assert data["status"] == "paid"
    assert data["subtotal_minor"] == 2 * 1999
    assert data["tax_minor"] == 800
    assert data["total_minor"] == data["subtotal_minor"] + data["tax_minor"]
    [item] = data["items"]
    assert item["quantity"] == 2
    assert item["unit_price_minor"] == 1999
    assert item["sku"].startswith("SKU-")
    assert data["tracking_number"] is None
    assert data["fulfilled_at"] is None
    assert data["oversold"] is False


async def test_an_oversold_order_is_flagged_in_detail_and_list(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    oversold_id = await place_order(client, world, store)
    normal_id = await place_order(client, world, store)
    async with open_store_session(store, world.provider) as session:
        await session.execute(
            text("UPDATE orders SET oversold = true WHERE id = :i"), {"i": oversold_id}
        )
        await session.commit()

    detail = await client.get(orders_url(store, f"/{oversold_id}"), headers=ALICE)
    listing = await client.get(orders_url(store), headers=ALICE)

    assert detail.json()["data"]["oversold"] is True
    flags = {row["id"]: row["oversold"] for row in listing.json()["data"]}
    assert (flags[oversold_id], flags[normal_id]) == (True, False)


async def test_an_unknown_order_is_a_fixed_404(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(orders_url(north(world), f"/{unique()}"), headers=ALICE)

    assert response.status_code == 404
    assert error_of(response) == "Order not found"


async def test_an_order_id_with_odd_characters_is_rejected(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(orders_url(north(world), "/a%20b"), headers=ALICE)

    assert response.status_code == 422


# --- fulfilment ----------------------------------------------------------------------


async def test_fulfilling_a_paid_order_records_tracking_and_carrier(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)

    response = await fulfil(
        client,
        store,
        order_id,
        {"tracking_number": "  1Z999AA10123456784  ", "carrier": " UPS "},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["status"] == "fulfilled"
    assert data["tracking_number"] == "1Z999AA10123456784"
    assert data["carrier"] == "UPS"
    assert data["fulfilled_at"] is not None
    assert len(data["items"]) == 1
    row = await stored_row(world, store, order_id)
    assert row["status"] == "fulfilled"
    assert row["fulfilled_at"] is not None
    read = await client.get(orders_url(store, f"/{order_id}"), headers=ALICE)
    assert read.json()["data"] == data


async def test_the_carrier_is_optional(client: AsyncClient, world: World) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)

    response = await fulfil(client, store, order_id, {"tracking_number": "T-9"})

    assert response.status_code == 200
    assert response.json()["data"]["carrier"] is None


async def test_a_pending_order_cannot_be_fulfilled(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    order_id = await place_order(client, world, store, paid=False)

    response = await fulfil(client, store, order_id)

    assert response.status_code == 409
    assert error_of(response) == GENERIC_409
    assert "pending" not in response.text
    assert (await stored_row(world, store, order_id))["status"] == "pending"


async def test_an_order_cannot_be_fulfilled_twice(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)
    first = await fulfil(client, store, order_id, {"tracking_number": "FIRST"})

    second = await fulfil(client, store, order_id, {"tracking_number": "SECOND"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert (await stored_row(world, store, order_id))["tracking_number"] == "FIRST"


async def test_fulfilling_an_unknown_order_is_a_404(
    client: AsyncClient, world: World
) -> None:
    response = await fulfil(client, north(world), unique())

    assert response.status_code == 404
    assert error_of(response) == "Order not found"


@pytest.mark.parametrize(
    "body",
    [
        {"tracking_number": ""},
        {"tracking_number": "   "},
        {"tracking_number": "x" * 101},
        {"tracking_number": "bad\nnumber"},
        {"tracking_number": "T-1", "carrier": "y" * 101},
        {"tracking_number": "T-1", "carrier": "bad\x00carrier"},
    ],
)
async def test_invalid_tracking_text_is_a_422_and_changes_nothing(
    client: AsyncClient, world: World, body: dict[str, Any]
) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)

    response = await fulfil(client, store, order_id, body)

    assert response.status_code == 422
    assert (await stored_row(world, store, order_id))["status"] == "paid"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"tracking_number": 12345},
        {"tracking_number": "T-1", "status": "refunded"},
        {"tracking_number": None},
    ],
)
async def test_a_malformed_fulfil_body_is_rejected(
    client: AsyncClient, world: World, body: dict[str, Any]
) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)

    response = await fulfil(client, store, order_id, body)

    assert response.status_code == 422
    assert (await stored_row(world, store, order_id))["status"] == "paid"


async def test_two_concurrent_fulfilments_exactly_one_wins(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)

    results = await asyncio.gather(
        fulfil(client, store, order_id, {"tracking_number": "RACE-A"}),
        fulfil(client, store, order_id, {"tracking_number": "RACE-B"}),
    )

    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r for r in results if r.status_code == 200)
    row = await stored_row(world, store, order_id)
    assert row["tracking_number"] == winner.json()["data"]["tracking_number"]


# --- tenant isolation ----------------------------------------------------------------


async def test_a_foreign_store_answers_like_a_missing_store(
    client: AsyncClient, world: World
) -> None:
    victim_store = store_of(world, "b", "north")
    victim_order = await place_order(client, world, victim_store, owner="bob")
    calls = (
        ("GET", "", None),
        ("GET", "/{o}", None),
        ("POST", "/{o}/fulfil", {"tracking_number": "HIJACK"}),
    )

    for method, suffix, body in calls:
        foreign = await client.request(
            method,
            orders_url(victim_store, suffix.format(o=victim_order)),
            json=body,
            headers=ALICE,
        )
        missing = await client.request(
            method,
            orders_url(unique(), suffix.format(o=unique())),
            json=body,
            headers=ALICE,
        )

        same_failure(foreign, missing)
        assert foreign.status_code == 404
        assert error_of(foreign) == "Store not found"
    assert (await stored_row(world, victim_store, victim_order))["status"] == "paid"


@pytest.mark.parametrize(
    ("own", "other"),
    [
        (("a", "north"), ("b", "north")),  # the other organisation's order id
        (("a", "north"), ("a", "south")),  # a sibling store of the same organisation
    ],
)
async def test_another_stores_order_id_under_the_callers_own_store_is_missing(
    client: AsyncClient, world: World, own: tuple[str, str], other: tuple[str, str]
) -> None:
    owner = "bob" if other[0] == "b" else "alice"
    other_store = store_of(world, *other)
    own_store = store_of(world, *own)
    order_id = await place_order(client, world, other_store, owner=owner)

    read = await client.get(orders_url(own_store, f"/{order_id}"), headers=ALICE)
    write = await fulfil(client, own_store, order_id)
    missing = await client.get(orders_url(own_store, f"/{unique()}"), headers=ALICE)

    same_failure(read, missing)
    assert (read.status_code, write.status_code) == (404, 404)
    assert error_of(write) == "Order not found"
    assert (await stored_row(world, other_store, order_id))["status"] == "paid"
    listed = await client.get(orders_url(own_store), headers=ALICE)
    assert order_id not in [o["id"] for o in listed.json()["data"]]


# --- roles, store status and failure modes -------------------------------------------


async def test_staff_can_read_but_not_fulfil(client: AsyncClient, world: World) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)

    listed = await client.get(orders_url(store), headers=AMY)
    read = await client.get(orders_url(store, f"/{order_id}"), headers=AMY)
    write = await fulfil(client, store, order_id, headers=AMY)

    assert (listed.status_code, read.status_code, write.status_code) == (200, 200, 403)
    assert (await stored_row(world, store, order_id))["status"] == "paid"


async def test_an_admin_can_fulfil(client: AsyncClient, world: World) -> None:
    store = north(world)
    order_id = await place_order(client, world, store)

    response = await fulfil(client, store, order_id, headers=DANA)

    assert response.status_code == 200


async def test_a_user_without_an_organisation_gets_not_found(
    client: AsyncClient, world: World
) -> None:
    store = north(world)

    read = await client.get(orders_url(store), headers=as_user("eve"))
    write = await fulfil(client, store, unique(), headers=as_user("eve"))

    assert (read.status_code, write.status_code) == (404, 404)
    same_failure(read, await client.get(orders_url(unique()), headers=as_user("eve")))


async def test_requests_need_the_internal_key_and_a_session(
    client: AsyncClient, world: World
) -> None:
    store = north(world)

    wrong_key = await client.get(
        orders_url(store), headers={**ALICE, "X-Internal-Key": "wrong"}
    )
    no_session = await client.get(orders_url(store))

    assert wrong_key.status_code == 401
    assert no_session.status_code == 401
    assert internal_key() not in wrong_key.text


async def test_a_suspended_store_can_be_read_but_not_fulfilled(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "b", "east")
    order_id = await place_order(client, world, store, owner="bob")
    await set_store_status(world, store, "SUSPENDED")
    try:
        read = await client.get(
            orders_url(store, f"/{order_id}"), headers=as_user("bob")
        )
        write = await fulfil(client, store, order_id, headers=as_user("bob"))
    finally:
        await set_store_status(world, store, "ACTIVE")

    assert (read.status_code, write.status_code) == (200, 403)
    assert error_of(write) == "Store is not active"
    assert (await stored_row(world, store, order_id))["status"] == "paid"


async def test_a_store_without_a_database_answers_a_fixed_503(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "east")  # never provisioned: no connection string

    response = await client.get(orders_url(store), headers=ALICE)

    assert response.status_code == 503
    assert error_of(response) == "Store database is not available"
    assert store not in response.text
    assert_no_database_text(response)


async def set_store_status(world: World, store_id: str, status: str) -> None:
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = :s WHERE id = :i"),
            {"s": status, "i": store_id},
        )
