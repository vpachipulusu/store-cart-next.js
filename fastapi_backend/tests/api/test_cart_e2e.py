"""Public shopper cart against real store databases (KAN-76).

The cart is keyed by an opaque token, prices and stock are re-read from the catalogue on every
call, totals use the store's shipping and tax settings, and one store's token or variants mean
nothing in another store. Runs only when ``TEST_DATABASE_URL`` points at a throwaway local
server (see ``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.services import store_cart
from app.services.store_sessions import open_store_session
from tests.api.products_support import (  # noqa: F401  (fixtures)
    assert_no_database_text,
    client,
    create_product,
    simple_payload,
    store_of,
    unique,
    variant_payload,
    world,
)
from tests.isolation_world import World, same_failure
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

TOKEN_HEADER = "X-Cart-Token"
NORTH_A = "a-north"
NORTH_B = "b-north"
NORTH = ("a", "north")


def cart_url(slug: str, suffix: str = "") -> str:
    return f"/v1/storefront/{slug}/cart{suffix}"


def with_token(token: str | None) -> dict[str, str]:
    return {TOKEN_HEADER: token} if token else {}


def data_of(response: Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def sellable_variant(
    client: AsyncClient, world: World, *, price: int = 1000, stock: int = 5
) -> str:
    """The variant id of a fresh active product in store a/north."""
    payload = simple_payload(
        status="active",
        variants=[variant_payload(unique(), price_minor=price, stock=stock)],
    )
    product = await create_product(client, store_of(world, *NORTH), "alice", payload)
    variant_id: str = product["variants"][0]["id"]
    return variant_id


async def run_sql(world: World, sql: str, **params: Any) -> None:
    async with open_store_session(store_of(world, *NORTH), world.provider) as session:
        await session.execute(text(sql), params)
        await session.commit()


async def cart_count(world: World) -> int:
    return int(
        await world.store_value(store_of(world, *NORTH), "SELECT count(*) FROM carts")
    )


async def add(
    client: AsyncClient,
    variant_id: str,
    quantity: int = 1,
    *,
    token: str | None = None,
    slug: str = NORTH_A,
) -> Response:
    return await client.post(
        cart_url(slug, "/items"),
        json={"variant_id": variant_id, "quantity": quantity},
        headers=with_token(token),
    )


async def read(
    client: AsyncClient, token: str | None, slug: str = NORTH_A
) -> dict[str, Any]:
    return data_of(await client.get(cart_url(slug), headers=with_token(token)))


async def test_adding_starts_a_cart_and_returns_its_token_once(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world, price=1000)

    first = data_of(await add(client, variant, 2))
    again = await read(client, first["cart_token"])

    assert len(first["cart_token"]) == 43
    assert first["lines"][0]["quantity"] == 2
    assert first["lines"][0]["unit_price_minor"] == 1000
    assert first["subtotal_minor"] == 2000
    assert first["can_checkout"] is True
    assert again["lines"] == first["lines"]
    assert again["cart_token"] is None


async def test_adding_again_adds_to_the_quantity_and_keeps_the_token(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world)
    token = data_of(await add(client, variant, 1))["cart_token"]

    second = data_of(await add(client, variant, 2, token=token))

    assert second["cart_token"] is None
    assert [line["quantity"] for line in second["lines"]] == [3]


async def test_the_token_is_stored_only_as_a_hash(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world)
    token = data_of(await add(client, variant))["cart_token"]

    async with open_store_session(store_of(world, *NORTH), world.provider) as db:
        hashes = (
            (await db.execute(text("SELECT token_hash FROM carts"))).scalars().all()
        )

    assert token not in hashes
    assert all(len(value) == 64 for value in hashes)


async def test_reading_without_a_cart_is_empty_and_creates_nothing(
    client: AsyncClient, world: World
) -> None:
    before = await cart_count(world)

    unknown = await read(client, "x" * 43)
    malformed = await read(client, "nope")

    assert unknown["lines"] == malformed["lines"] == []
    assert unknown["can_checkout"] is False
    assert unknown["total_minor"] == 0
    assert await cart_count(world) == before


async def test_a_price_change_shows_on_the_next_read(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world, price=1000)
    token = data_of(await add(client, variant, 2))["cart_token"]

    await run_sql(
        world, "UPDATE variants SET price_minor = 1500 WHERE id = :v", v=variant
    )
    after = await read(client, token)

    assert after["lines"][0]["unit_price_minor"] == 1500
    assert after["subtotal_minor"] == 3000


async def test_a_client_cannot_send_a_price(client: AsyncClient, world: World) -> None:
    variant = await sellable_variant(client, world)

    response = await client.post(
        cart_url(NORTH_A, "/items"),
        json={"variant_id": variant, "quantity": 1, "unit_price_minor": 1},
    )

    assert response.status_code == 422


async def test_shipping_and_tax_come_from_the_store_settings(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world, price=1000)
    await run_sql(
        world,
        "UPDATE store_settings SET shipping_flat_rate_minor = 499, tax_rate_bps = 2000",
    )
    try:
        cart = data_of(await add(client, variant, 2))
    finally:
        await run_sql(
            world,
            "UPDATE store_settings SET shipping_flat_rate_minor = 0, tax_rate_bps = 0",
        )

    assert cart["subtotal_minor"] == 2000
    assert cart["shipping_minor"] == 499
    assert cart["tax_minor"] == 400
    assert cart["total_minor"] == 2899


@pytest.mark.parametrize("quantity", [0, 100, -1, "2", 1.5])
async def test_quantity_must_be_a_whole_number_from_1_to_99(
    client: AsyncClient, world: World, quantity: Any
) -> None:
    variant = await sellable_variant(client, world)

    response = await client.post(
        cart_url(NORTH_A, "/items"), json={"variant_id": variant, "quantity": quantity}
    )

    assert response.status_code == 422


async def test_adding_more_than_the_stock_is_refused(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world, stock=3)
    token = data_of(await add(client, variant, 2))["cart_token"]

    over = await add(client, variant, 2, token=token)
    set_over = await client.put(
        cart_url(NORTH_A, f"/items/{variant}"),
        json={"quantity": 4},
        headers=with_token(token),
    )
    kept = await read(client, token)

    assert over.status_code == set_over.status_code == 409
    assert over.json()["error"] == "Only 3 in stock"
    assert [line["quantity"] for line in kept["lines"]] == [2]
    assert_no_database_text(over)


async def test_a_variant_with_no_stock_is_refused(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world, stock=0)

    response = await add(client, variant)

    assert response.status_code == 409
    assert response.json()["error"] == "That item is out of stock"


async def test_stock_dropping_after_adding_flags_the_line_and_leaves_it_out_of_the_totals(
    client: AsyncClient, world: World
) -> None:
    kept = await sellable_variant(client, world, price=1000, stock=9)
    limited = await sellable_variant(client, world, price=500, stock=9)
    gone = await sellable_variant(client, world, price=700, stock=9)
    token = data_of(await add(client, kept, 1))["cart_token"]
    await add(client, limited, 4, token=token)
    await add(client, gone, 1, token=token)
    await run_sql(world, "UPDATE variants SET stock = 2 WHERE id = :v", v=limited)
    await run_sql(world, "UPDATE variants SET stock = 0 WHERE id = :v", v=gone)

    cart = await read(client, token)

    statuses = {line["variant_id"]: line["status"] for line in cart["lines"]}
    assert statuses == {kept: "ok", limited: "limited", gone: "out_of_stock"}
    assert cart["subtotal_minor"] == 1000
    assert cart["can_checkout"] is False


async def test_unpublishing_a_product_marks_its_line_unavailable(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world)
    token = data_of(await add(client, variant))["cart_token"]

    await run_sql(
        world,
        "UPDATE products SET status = 'draft' "
        "WHERE id = (SELECT product_id FROM variants WHERE id = :v)",
        v=variant,
    )
    cart = await read(client, token)

    assert cart["lines"][0]["status"] == "unavailable"
    assert cart["subtotal_minor"] == 0
    assert cart["can_checkout"] is False


async def test_a_deleted_variant_leaves_the_cart(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world)
    token = data_of(await add(client, variant))["cart_token"]

    await run_sql(world, "DELETE FROM variants WHERE id = :v", v=variant)

    assert (await read(client, token))["lines"] == []


async def test_a_draft_or_unknown_variant_cannot_be_added(
    client: AsyncClient, world: World
) -> None:
    draft = await create_product(
        client, store_of(world, *NORTH), "alice", simple_payload()
    )

    draft_response = await add(client, draft["variants"][0]["id"])
    unknown_response = await add(client, "no-such-variant")

    same_failure(draft_response, unknown_response)
    assert draft_response.status_code == 404


async def test_set_quantity_and_remove(client: AsyncClient, world: World) -> None:
    variant = await sellable_variant(client, world)
    token = data_of(await add(client, variant, 1))["cart_token"]

    changed = data_of(
        await client.put(
            cart_url(NORTH_A, f"/items/{variant}"),
            json={"quantity": 4},
            headers=with_token(token),
        )
    )
    removed = data_of(
        await client.delete(
            cart_url(NORTH_A, f"/items/{variant}"), headers=with_token(token)
        )
    )

    assert [line["quantity"] for line in changed["lines"]] == [4]
    assert removed["lines"] == []
    assert removed["cart_token"] is None


async def test_removing_without_a_cart_creates_none(
    client: AsyncClient, world: World
) -> None:
    before = await cart_count(world)

    response = await client.delete(cart_url(NORTH_A, "/items/anything"))

    assert data_of(response)["lines"] == []
    assert await cart_count(world) == before


async def test_an_expired_cart_reads_empty_and_a_write_starts_a_new_one(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world)
    token = data_of(await add(client, variant))["cart_token"]
    await run_sql(world, "UPDATE carts SET expires_at = now() - interval '1 minute'")

    empty = await read(client, token)
    rewritten = data_of(await add(client, variant, 1, token=token))

    assert empty["lines"] == []
    assert rewritten["cart_token"] not in (None, token)
    assert [line["quantity"] for line in rewritten["lines"]] == [1]


async def test_a_cart_holds_a_limited_number_of_lines(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_cart, "MAX_LINES", 2)
    first, second, third = [await sellable_variant(client, world) for _ in range(3)]
    token = data_of(await add(client, first))["cart_token"]
    await add(client, second, token=token)

    refused = await add(client, third, token=token)
    same_line_again = await add(client, first, token=token)

    assert refused.status_code == 409
    assert same_line_again.status_code == 200


async def test_a_token_from_one_store_is_nothing_in_another(
    client: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(client, world)
    token = data_of(await add(client, variant))["cart_token"]

    elsewhere = await read(client, token, slug=NORTH_B)
    foreign_variant = await add(client, variant, slug=NORTH_B)

    assert elsewhere["lines"] == []
    assert foreign_variant.status_code == 404


async def test_a_store_that_is_not_live_is_the_same_404_as_an_unknown_one(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "b", "south")
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = 'SUSPENDED' WHERE id = :i"), {"i": store}
        )
    try:
        suspended = await client.get(cart_url("b-south"))
        unknown = await client.get(cart_url("never-existed"))
        reserved = await client.get(cart_url("admin"))
    finally:
        async with world.platform.begin() as connection:
            await connection.execute(
                text("UPDATE stores SET status = 'ACTIVE' WHERE id = :i"), {"i": store}
            )

    same_failure(suspended, unknown)
    same_failure(reserved, unknown)
    assert unknown.status_code == 404


async def test_a_live_store_without_a_database_is_a_503(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(cart_url("a-east"))

    assert response.status_code == 503
    assert_no_database_text(response)


async def test_responses_are_never_cached(client: AsyncClient, world: World) -> None:
    variant = await sellable_variant(client, world)

    written = await add(client, variant)
    read_response = await client.get(cart_url(NORTH_A))
    refused = await add(client, "no-such-variant")

    assert written.headers["cache-control"] == "no-store"
    assert read_response.headers["cache-control"] == "no-store"
    assert refused.headers["cache-control"] == "no-store"


async def test_the_internal_key_is_required(client: AsyncClient) -> None:
    response = await client.get(cart_url(NORTH_A), headers={"X-Internal-Key": "wrong"})

    assert response.status_code == 401
