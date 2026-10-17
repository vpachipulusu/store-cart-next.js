"""Product API: limits, error headers, ordering and orders after review (KAN-245).

Companion to ``test_products_e2e.py`` (kept apart so neither file grows past the size
ceiling). Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

import json
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.store_orders import OrderLineInput, create_order
from app.services.store_sessions import open_store_session
from tests.api.products_support import (  # noqa: F401  (fixtures)
    LISTING_STORE,
    as_user,
    assert_no_database_text,
    client,
    create_product,
    error_of,
    product_payload,
    products_url,
    simple_payload,
    store_of,
    unique,
    variant_payload,
    world,
)
from tests.isolation_world import World
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

ALICE = as_user("alice")
BOB = as_user("bob")


def north(world: World) -> str:
    return store_of(world, "a", "north")


async def test_values_at_their_limits_are_accepted_and_stored(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    tag = unique()
    payload = simple_payload(
        title="é" * 255,
        slug=f"{tag}-" + "s" * (200 - len(tag) - 1),
        description="d" * 10_000,
        variants=[
            variant_payload(
                f"{tag}-" + "K" * (100 - len("SKU-") - len(tag) - 1),
                price_minor=2**53 - 1,
                stock=1_000_000_000,
                weight_grams=1_000_000_000,
            )
        ],
    )
    created = await create_product(client, store, "alice", payload)
    free = await create_product(
        client,
        store,
        "alice",
        simple_payload(variants=[variant_payload(unique(), price_minor=0)]),
    )
    prefix = f"stores/{store}/"
    key = prefix + "a" * (255 - len(prefix) - 4) + ".png"
    attached = await client.post(
        products_url(store, f"/{free['id']}/images"),
        json={"storage_key": key, "alt_text": "x" * 500},
        headers=ALICE,
    )
    too_long = await client.post(
        products_url(store, f"/{free['id']}/images"),
        json={"storage_key": key[:-4] + "a.png"},
        headers=ALICE,
    )

    variant = created["variants"][0]
    assert (variant["price_minor"], variant["stock"]) == (2**53 - 1, 1_000_000_000)
    assert variant["weight_grams"] == 1_000_000_000
    assert len(created["title"]) == 255
    assert len(created["slug"]) == 200
    assert free["variants"][0]["price_minor"] == 0
    assert attached.status_code == 201
    assert too_long.status_code == 422


@pytest.mark.parametrize("field", ["title", "description"])
async def test_lone_surrogates_are_a_422_not_a_500(
    client: AsyncClient, world: World, field: str
) -> None:
    payload: dict[str, Any] = {**simple_payload(), field: "bad\ud800"}

    response = await client.post(
        products_url(north(world)),
        content=json.dumps(payload),
        headers={**ALICE, "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert_no_database_text(response)


async def test_a_sku_with_an_invisible_character_is_rejected(
    client: AsyncClient, world: World
) -> None:
    response = await client.post(
        products_url(north(world)),
        json=simple_payload(variants=[variant_payload("AB\u200bCD" + unique())]),
        headers=ALICE,
    )

    assert response.status_code == 422
    assert "invisible" in error_of(response)


async def test_a_huge_offset_is_a_422_not_a_500(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(
        products_url(north(world), "?offset=99999999999999999999"), headers=ALICE
    )

    assert response.status_code == 422


async def test_error_responses_are_not_cacheable(
    client: AsyncClient, world: World
) -> None:
    taken = await create_product(client, north(world), "alice", simple_payload())

    missing = await client.get(
        products_url(north(world), f"/{unique()}"), headers=ALICE
    )
    conflict = await client.post(
        products_url(north(world)),
        json=simple_payload(slug=taken["slug"]),
        headers=ALICE,
    )

    assert missing.status_code == 404
    assert conflict.status_code == 409
    assert missing.headers["cache-control"] == "no-store"
    assert conflict.headers["cache-control"] == "no-store"


async def test_add_variant_with_a_taken_sku_is_a_409(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    other = await create_product(client, store, "alice", simple_payload())
    created = await create_product(client, store, "alice")

    response = await client.post(
        products_url(store, f"/{created['id']}/variants"),
        json=variant_payload(
            other["variants"][0]["sku"].lower(), options={"Size": "S"}
        ),
        headers=ALICE,
    )

    assert response.status_code == 409


async def test_a_slug_is_unique_per_store_not_per_platform(
    client: AsyncClient, world: World
) -> None:
    slug = f"shared-{unique()}"
    await create_product(client, north(world), "alice", simple_payload(slug=slug))

    elsewhere = await client.post(
        products_url(store_of(world, "b", "north")),
        json=simple_payload(slug=slug),
        headers=BOB,
    )

    assert elsewhere.status_code == 201


async def test_list_is_newest_first(client: AsyncClient, world: World) -> None:
    store = store_of(world, *LISTING_STORE)
    made = [
        (await create_product(client, store, "bob", simple_payload()))["id"]
        for _ in range(3)
    ]

    listing = await client.get(products_url(store, "?limit=100"), headers=BOB)

    ids = [p["id"] for p in listing.json()["data"]]
    assert [i for i in ids if i in made] == list(reversed(made))


async def test_deleting_a_variant_keeps_the_orders_that_bought_it(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(
        client, store, "alice", product_payload(status="active")
    )
    sold, kept = created["variants"]
    async with open_store_session(store, world.provider) as session:
        order = await create_order(
            session,
            currency="USD",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=sold["id"], quantity=1)],
        )
        await session.commit()

    deleted = await client.delete(
        products_url(store, f"/{created['id']}/variants/{sold['id']}"), headers=ALICE
    )

    assert deleted.status_code == 200
    assert [v["id"] for v in deleted.json()["data"]["variants"]] == [kept["id"]]
    row = await world.store_value(
        store,
        "SELECT sku || '|' || coalesce(variant_id, 'null') || '|' || "
        "(product_id IS NOT NULL)::text FROM order_items "
        f"WHERE order_id = '{order.id}'",
    )
    assert row == f"{sold['sku']}|null|true"


async def test_two_variants_sharing_a_combination_in_one_create_is_a_409(
    client: AsyncClient, world: World
) -> None:
    response = await client.post(
        products_url(north(world)),
        json=product_payload(
            variants=[
                variant_payload(unique(), options={"Size": "S"}),
                variant_payload(unique(), options={"Size": "s"}),
            ]
        ),
        headers=ALICE,
    )

    assert response.status_code == 409
    assert error_of(response) == "Two variants have the same options"
