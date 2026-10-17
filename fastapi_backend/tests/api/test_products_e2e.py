"""Product, variant and image routes against real store databases (KAN-245).

CRUD, validation, conflicts, paging and filters, variants and images. Cross-store
isolation, roles and failure modes are in ``test_products_isolation_e2e.py``. Runs only when
``TEST_DATABASE_URL`` points at a throwaway local server (see ``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.store_orders import OrderLineInput, create_order
from app.services.store_sessions import open_store_session
from tests.api.products_support import (  # noqa: F401  (fixtures)
    LISTING_STORE,
    add_category,
    as_user,
    assert_no_database_text,
    client,
    create_product,
    error_of,
    product_payload,
    products_url,
    simple_payload,
    store_count,
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


# --- create and read -----------------------------------------------------------------


async def test_create_returns_the_whole_product(
    client: AsyncClient, world: World
) -> None:
    payload = product_payload()

    response = await client.post(
        products_url(north(world)), json=payload, headers=ALICE
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["title"] == payload["title"]
    assert data["slug"] == payload["slug"]
    assert data["status"] == "draft"
    assert data["currency"] == "USD"
    [option] = data["options"]
    assert [v["value"] for v in option["values"]] == ["S", "M"]
    assert [v["sku"] for v in data["variants"]] == [
        v["sku"] for v in payload["variants"]
    ]
    for variant in data["variants"]:
        assert [c["option_id"] for c in variant["option_values"]] == [option["id"]]
    assert data["images"] == []
    assert data["category_ids"] == []


async def test_get_returns_what_create_returned(
    client: AsyncClient, world: World
) -> None:
    created = await create_product(client, north(world), "alice")

    response = await client.get(
        products_url(north(world), f"/{created['id']}"), headers=ALICE
    )

    assert response.status_code == 200
    assert response.json()["data"] == created


async def test_create_without_options_makes_one_default_variant(
    client: AsyncClient, world: World
) -> None:
    created = await create_product(client, north(world), "alice", simple_payload())

    assert created["options"] == []
    [variant] = created["variants"]
    assert variant["option_values"] == []


async def test_slug_is_derived_from_the_title_when_omitted(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    payload = simple_payload(title=f"  Crème Brûlée Mug {tag}!  ")
    del payload["slug"]

    created = await create_product(client, north(world), "alice", payload)

    assert created["slug"] == f"creme-brulee-mug-{tag}"
    assert created["title"] == f"Crème Brûlée Mug {tag}!"


async def test_title_without_usable_characters_needs_an_explicit_slug(
    client: AsyncClient, world: World
) -> None:
    payload = simple_payload(title="!!! ???")
    del payload["slug"]

    response = await client.post(
        products_url(north(world)), json=payload, headers=ALICE
    )

    assert response.status_code == 422
    assert "slug" in error_of(response).lower()


async def test_category_assignments_are_stored_and_returned(
    client: AsyncClient, world: World
) -> None:
    first = await add_category(world, north(world))
    second = await add_category(world, north(world))

    created = await create_product(
        client,
        north(world),
        "alice",
        simple_payload(category_ids=[second, first, first]),
    )

    assert created["category_ids"] == sorted([first, second])


async def test_equal_compare_at_price_means_no_sale(
    client: AsyncClient, world: World
) -> None:
    payload = simple_payload()
    payload["variants"][0].update(price_minor=500, compare_at_price_minor=500)

    created = await create_product(client, north(world), "alice", payload)

    assert created["variants"][0]["compare_at_price_minor"] is None


async def test_compare_at_price_above_the_price_is_kept(
    client: AsyncClient, world: World
) -> None:
    payload = simple_payload()
    payload["variants"][0].update(price_minor=500, compare_at_price_minor=900)

    created = await create_product(client, north(world), "alice", payload)

    assert created["variants"][0]["compare_at_price_minor"] == 900


# --- validation (422) ----------------------------------------------------------------


def with_variant(**over: Any) -> dict[str, Any]:
    payload = simple_payload()
    payload["variants"][0].update(over)
    return payload


INVALID_BODIES: list[tuple[str, dict[str, Any]]] = [
    ("negative price", with_variant(price_minor=-1)),
    ("fractional price", with_variant(price_minor=1.5)),
    ("string price", with_variant(price_minor="10")),
    ("boolean price", with_variant(price_minor=True)),
    ("price above the cap", with_variant(price_minor=2**53)),
    (
        "compare-at below price",
        with_variant(price_minor=500, compare_at_price_minor=100),
    ),
    ("negative stock", with_variant(stock=-1)),
    ("stock above the cap", with_variant(stock=2_000_000_000)),
    ("negative weight", with_variant(weight_grams=-5)),
    ("blank sku", with_variant(sku="   ")),
    ("sku with newline", with_variant(sku="AB\nCD")),
    ("sku too long", with_variant(sku="S" * 101)),
    ("unknown variant field", with_variant(colour="red")),
    ("blank title", simple_payload(title="  ")),
    ("title too long", simple_payload(title="T" * 256)),
    ("title with control character", simple_payload(title="Mug\x07")),
    ("title with NUL", simple_payload(title="Mug\x00")),
    ("description too long", simple_payload(description="d" * 10_001)),
    ("slug with capitals", simple_payload(slug="Mug")),
    ("slug with spaces", simple_payload(slug="my mug")),
    ("slug with double hyphen", simple_payload(slug="my--mug")),
    ("slug too long", simple_payload(slug="s" * 201)),
    ("unknown status", simple_payload(status="archived")),
    ("unknown top-level field", simple_payload(store_id="other")),
    ("no variants", simple_payload(variants=[])),
    (
        "two variants without options",
        simple_payload(variants=[variant_payload(unique()), variant_payload(unique())]),
    ),
    (
        "duplicate option names",
        product_payload(
            options=[
                {"name": "Size", "values": ["S"]},
                {"name": "size", "values": ["M"]},
            ]
        ),
    ),
    (
        "duplicate option values",
        product_payload(options=[{"name": "Size", "values": ["S", "s"]}]),
    ),
    (
        "option without values",
        product_payload(options=[{"name": "Size", "values": []}]),
    ),
    (
        "four options",
        product_payload(options=[{"name": f"O{i}", "values": ["a"]} for i in range(4)]),
    ),
    (
        "variant misses an option",
        product_payload(variants=[variant_payload(unique(), options={})]),
    ),
    (
        "variant picks unknown value",
        product_payload(variants=[variant_payload(unique(), options={"Size": "XXL"})]),
    ),
    (
        "variant picks unknown option",
        product_payload(
            variants=[variant_payload(unique(), options={"Size": "S", "Colour": "Red"})]
        ),
    ),
    ("unknown category", simple_payload(category_ids=["nope"])),
    ("category id with NUL", simple_payload(category_ids=["a\x00b"])),
]


@pytest.mark.parametrize(
    "body", [b for _, b in INVALID_BODIES], ids=[name for name, _ in INVALID_BODIES]
)
async def test_invalid_input_is_a_curated_422_and_writes_nothing(
    client: AsyncClient, world: World, body: dict[str, Any]
) -> None:
    store = north(world)
    before = await store_count(world, store, "SELECT count(*) FROM products")

    response = await client.post(products_url(store), json=body, headers=ALICE)

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert_no_database_text(response)
    assert await store_count(world, store, "SELECT count(*) FROM products") == before


async def test_unreadable_json_is_a_422_not_a_500(
    client: AsyncClient, world: World
) -> None:
    response = await client.post(
        products_url(north(world)),
        content=b'{"title": ',
        headers={**ALICE, "Content-Type": "application/json"},
    )

    assert response.status_code == 422


# --- conflicts (409) -----------------------------------------------------------------


async def test_a_taken_slug_is_a_409_without_database_text(
    client: AsyncClient, world: World
) -> None:
    first = await create_product(client, north(world), "alice", simple_payload())

    response = await client.post(
        products_url(north(world)),
        json=simple_payload(slug=first["slug"]),
        headers=ALICE,
    )

    assert response.status_code == 409
    assert error_of(response) == "Slug is already in use"
    assert_no_database_text(response)


async def test_sku_is_unique_per_store_ignoring_case(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    await create_product(
        client,
        north(world),
        "alice",
        simple_payload(variants=[variant_payload(f"Ab-{tag}")]),
    )

    clash = await client.post(
        products_url(north(world)),
        json=simple_payload(variants=[variant_payload(f"aB-{tag}")]),
        headers=ALICE,
    )
    other_store = await client.post(
        products_url(store_of(world, "b", "north")),
        json=simple_payload(variants=[variant_payload(f"Ab-{tag}")]),
        headers=BOB,
    )

    assert clash.status_code == 409
    assert error_of(clash) == "SKU is already in use"
    assert_no_database_text(clash)
    assert other_store.status_code == 201  # unique per store, not per platform


async def test_the_same_sku_twice_in_one_request_is_a_409(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    payload = product_payload(
        variants=[
            variant_payload(f"dup-{tag}", options={"Size": "S"}),
            variant_payload(f"DUP-{tag}", options={"Size": "M"}),
        ]
    )

    response = await client.post(
        products_url(north(world)), json=payload, headers=ALICE
    )

    assert response.status_code == 409


async def test_a_failed_create_leaves_no_partial_product(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    first = await create_product(
        client,
        north(world),
        "alice",
        simple_payload(variants=[variant_payload(f"k-{tag}")]),
    )
    doomed = product_payload(
        variants=[
            variant_payload(f"new-{tag}", options={"Size": "S"}),
            variant_payload(f"k-{tag}", options={"Size": "M"}),
        ]
    )

    response = await client.post(products_url(north(world)), json=doomed, headers=ALICE)

    assert response.status_code == 409
    leftovers = await store_count(
        world,
        north(world),
        f"SELECT count(*) FROM products WHERE slug = '{doomed['slug']}'",
    )
    assert leftovers == 0
    assert first["slug"]


async def test_concurrent_creates_of_one_sku_let_exactly_one_win(
    client: AsyncClient, world: World
) -> None:
    tag = unique()

    responses = await asyncio.gather(
        *(
            client.post(
                products_url(north(world)),
                json=simple_payload(variants=[variant_payload(f"race-{tag}")]),
                headers=ALICE,
            )
            for _ in range(4)
        )
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409]


# --- update --------------------------------------------------------------------------


async def test_patch_changes_only_the_sent_fields(
    client: AsyncClient, world: World
) -> None:
    created = await create_product(client, north(world), "alice")

    response = await client.patch(
        products_url(north(world), f"/{created['id']}"),
        json={"title": "Renamed", "status": "active"},
        headers=ALICE,
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert (data["title"], data["status"]) == ("Renamed", "active")
    assert data["slug"] == created["slug"]
    assert data["description"] == created["description"]
    assert data["updated_at"] >= created["updated_at"]


async def test_patch_can_clear_the_description_and_unpublish(
    client: AsyncClient, world: World
) -> None:
    created = await create_product(
        client, north(world), "alice", simple_payload(status="active")
    )

    response = await client.patch(
        products_url(north(world), f"/{created['id']}"),
        json={"description": None, "status": "draft"},
        headers=ALICE,
    )

    data = response.json()["data"]
    assert (data["description"], data["status"]) == (None, "draft")


async def test_patch_replaces_the_category_set(
    client: AsyncClient, world: World
) -> None:
    first = await add_category(world, north(world))
    second = await add_category(world, north(world))
    created = await create_product(
        client, north(world), "alice", simple_payload(category_ids=[first])
    )

    swapped = await client.patch(
        products_url(north(world), f"/{created['id']}"),
        json={"category_ids": [second]},
        headers=ALICE,
    )
    cleared = await client.patch(
        products_url(north(world), f"/{created['id']}"),
        json={"category_ids": []},
        headers=ALICE,
    )

    assert swapped.json()["data"]["category_ids"] == [second]
    assert cleared.json()["data"]["category_ids"] == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": None},
        {"title": ""},
        {"slug": "Bad Slug"},
        {"status": "archived"},
        {"status": None},
        {"category_ids": ["missing"]},
        {"store_id": "x"},
    ],
)
async def test_patch_rejects_bad_input_with_422(
    client: AsyncClient, world: World, body: dict[str, Any]
) -> None:
    created = await create_product(client, north(world), "alice")

    response = await client.patch(
        products_url(north(world), f"/{created['id']}"), json=body, headers=ALICE
    )

    assert response.status_code == 422
    assert_no_database_text(response)


async def test_patch_to_a_taken_slug_is_a_409_and_changes_nothing(
    client: AsyncClient, world: World
) -> None:
    first = await create_product(client, north(world), "alice")
    second = await create_product(client, north(world), "alice")

    response = await client.patch(
        products_url(north(world), f"/{second['id']}"),
        json={"slug": first["slug"], "title": "Changed"},
        headers=ALICE,
    )

    again = await client.get(
        products_url(north(world), f"/{second['id']}"), headers=ALICE
    )
    assert response.status_code == 409
    assert again.json()["data"]["title"] == second["title"]


async def test_unknown_product_is_404_for_every_product_route(
    client: AsyncClient, world: World
) -> None:
    missing = unique()
    base = products_url(north(world), f"/{missing}")

    responses = [
        await client.get(base, headers=ALICE),
        await client.patch(base, json={"title": "x"}, headers=ALICE),
        await client.delete(base, headers=ALICE),
        await client.post(f"{base}/variants", json=variant_payload("x"), headers=ALICE),
        await client.patch(
            f"{base}/variants/{missing}", json={"stock": 1}, headers=ALICE
        ),
        await client.delete(f"{base}/variants/{missing}", headers=ALICE),
        await client.post(
            f"{base}/images",
            json={"storage_key": f"stores/{north(world)}/abc.png"},
            headers=ALICE,
        ),
        await client.delete(f"{base}/images/{missing}", headers=ALICE),
    ]

    assert {r.status_code for r in responses} == {404}
    assert {error_of(r) for r in responses} == {"Product not found"}


@pytest.mark.parametrize("bad_id", ["%00", "a%20b", "x" * 101, "a.b"])
async def test_malformed_ids_are_rejected_before_the_database(
    client: AsyncClient, world: World, bad_id: str
) -> None:
    response = await client.get(products_url(north(world), f"/{bad_id}"), headers=ALICE)

    assert response.status_code in {404, 422}
    assert_no_database_text(response)


# --- delete --------------------------------------------------------------------------


async def test_delete_removes_the_product_with_its_children(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")
    await client.post(
        products_url(store, f"/{created['id']}/images"),
        json={"storage_key": f"stores/{store}/img{unique()}.png"},
        headers=ALICE,
    )

    response = await client.delete(
        products_url(store, f"/{created['id']}"), headers=ALICE
    )
    gone = await client.get(products_url(store, f"/{created['id']}"), headers=ALICE)

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert gone.status_code == 404
    pid = created["id"]
    for table, column in (
        ("variants", "product_id"),
        ("product_options", "product_id"),
        ("product_images", "product_id"),
    ):
        assert (
            await store_count(
                world, store, f"SELECT count(*) FROM {table} WHERE {column} = '{pid}'"
            )
            == 0
        )


async def test_deleting_a_product_keeps_the_orders_that_bought_it(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(
        client, store, "alice", simple_payload(status="active")
    )
    variant = created["variants"][0]
    async with open_store_session(store, world.provider) as session:
        order = await create_order(
            session,
            currency="USD",
            tax_rate_bps=2000,
            lines=[OrderLineInput(variant_id=variant["id"], quantity=2)],
        )
        await session.commit()

    deleted = await client.delete(
        products_url(store, f"/{created['id']}"), headers=ALICE
    )

    assert deleted.status_code == 204
    item = await world.store_value(
        store,
        "SELECT product_name || '|' || sku || '|' || unit_price_minor || '|' || "
        "coalesce(product_id, 'null') || '|' || coalesce(variant_id, 'null') "
        f"FROM order_items WHERE order_id = '{order.id}'",
    )
    assert (
        item
        == f"{created['title']}|{variant['sku']}|{variant['price_minor']}|null|null"
    )


# --- listing -------------------------------------------------------------------------


async def test_list_pages_filters_and_counts(client: AsyncClient, world: World) -> None:
    store = store_of(world, *LISTING_STORE)
    category = await add_category(world, store)
    for index in range(5):
        await create_product(
            client,
            store,
            "bob",
            simple_payload(
                status="active" if index % 2 == 0 else "draft",
                category_ids=[category] if index < 2 else [],
            ),
        )

    everything = await client.get(products_url(store), headers=BOB)
    page = await client.get(products_url(store, "?limit=2&offset=2"), headers=BOB)
    past_the_end = await client.get(products_url(store, "?offset=50"), headers=BOB)
    active = await client.get(products_url(store, "?status=active"), headers=BOB)
    drafts = await client.get(products_url(store, "?status=draft"), headers=BOB)
    in_category = await client.get(
        products_url(store, f"?category_id={category}"), headers=BOB
    )
    unknown_category = await client.get(
        products_url(store, "?category_id=nothing"), headers=BOB
    )

    total = everything.json()["total"]
    assert everything.status_code == 200
    assert total == 5
    assert everything.json()["currency"] == "USD"
    assert len(everything.json()["data"]) == 5
    assert page.json()["total"] == 5
    assert (page.json()["limit"], page.json()["offset"]) == (2, 2)
    assert [p["id"] for p in page.json()["data"]] == [
        p["id"] for p in everything.json()["data"][2:4]
    ]
    assert past_the_end.json()["data"] == []
    assert active.json()["total"] == 3
    assert drafts.json()["total"] == 2
    assert in_category.json()["total"] == 2
    assert unknown_category.json()["data"] == []
    assert everything.headers["cache-control"] == "no-store"


async def test_list_summary_has_variant_count_and_price_range(
    client: AsyncClient, world: World
) -> None:
    created = await create_product(client, north(world), "alice")

    listing = await client.get(products_url(north(world), "?limit=100"), headers=ALICE)

    row = next(p for p in listing.json()["data"] if p["id"] == created["id"])
    assert row["variant_count"] == 2
    assert (row["min_price_minor"], row["max_price_minor"]) == (1999, 2199)


@pytest.mark.parametrize(
    "query", ["?limit=0", "?limit=101", "?offset=-1", "?status=archived", "?limit=x"]
)
async def test_list_rejects_bad_paging_and_filters(
    client: AsyncClient, world: World, query: str
) -> None:
    response = await client.get(products_url(north(world), query), headers=ALICE)

    assert response.status_code == 422


# --- variants ------------------------------------------------------------------------


async def test_add_variant_after_create(client: AsyncClient, world: World) -> None:
    store = north(world)
    created = await create_product(
        client,
        store,
        "alice",
        product_payload(
            options=[{"name": "Size", "values": ["S", "M", "L"]}],
            variants=[variant_payload(unique(), options={"Size": "S"})],
        ),
    )

    response = await client.post(
        products_url(store, f"/{created['id']}/variants"),
        json=variant_payload(unique(), options={"size": "l"}),
        headers=ALICE,
    )

    assert response.status_code == 201
    variants = response.json()["data"]["variants"]
    assert len(variants) == 2
    assert variants[1]["position"] == 1


@pytest.mark.parametrize(
    ("options", "status"),
    [
        ({"Size": "S"}, 409),  # combination exists
        ({}, 422),  # misses the option
        ({"Size": "XL"}, 422),  # unknown value
    ],
)
async def test_add_variant_enforces_the_option_rules(
    client: AsyncClient, world: World, options: dict[str, str], status: int
) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")

    response = await client.post(
        products_url(store, f"/{created['id']}/variants"),
        json=variant_payload(unique(), options=options),
        headers=ALICE,
    )

    assert response.status_code == status
    assert_no_database_text(response)


async def test_a_product_without_options_cannot_get_a_second_variant(
    client: AsyncClient, world: World
) -> None:
    created = await create_product(client, north(world), "alice", simple_payload())

    response = await client.post(
        products_url(north(world), f"/{created['id']}/variants"),
        json=variant_payload(unique()),
        headers=ALICE,
    )

    assert response.status_code == 422


async def test_concurrent_adds_of_one_combination_let_one_win(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(
        client,
        store,
        "alice",
        product_payload(
            options=[{"name": "Size", "values": ["S", "M"]}],
            variants=[variant_payload(unique(), options={"Size": "S"})],
        ),
    )

    responses = await asyncio.gather(
        *(
            client.post(
                products_url(store, f"/{created['id']}/variants"),
                json=variant_payload(unique(), options={"Size": "M"}),
                headers=ALICE,
            )
            for _ in range(3)
        )
    )

    assert sorted(r.status_code for r in responses) == [201, 409, 409]


async def test_update_variant_changes_price_stock_and_weight(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")
    variant = created["variants"][0]

    response = await client.patch(
        products_url(store, f"/{created['id']}/variants/{variant['id']}"),
        json={
            "price_minor": 1000,
            "compare_at_price_minor": 1500,
            "stock": 0,
            "weight_grams": 250,
        },
        headers=ALICE,
    )

    updated = response.json()["data"]["variants"][0]
    assert response.status_code == 200
    assert (updated["price_minor"], updated["compare_at_price_minor"]) == (1000, 1500)
    assert (updated["stock"], updated["weight_grams"]) == (0, 250)


async def test_update_variant_checks_compare_at_against_the_stored_price(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    payload = simple_payload()
    payload["variants"][0].update(price_minor=500, compare_at_price_minor=900)
    created = await create_product(client, store, "alice", payload)
    path = products_url(
        store, f"/{created['id']}/variants/{created['variants'][0]['id']}"
    )

    too_high = await client.patch(path, json={"price_minor": 1200}, headers=ALICE)
    equal = await client.patch(path, json={"price_minor": 900}, headers=ALICE)
    cleared = await client.patch(path, json={"weight_grams": None}, headers=ALICE)

    assert too_high.status_code == 422
    assert equal.json()["data"]["variants"][0]["compare_at_price_minor"] is None
    assert cleared.status_code == 200


async def test_update_variant_sku_conflicts_with_another_product(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    first = await create_product(client, store, "alice", simple_payload())
    second = await create_product(client, store, "alice", simple_payload())

    response = await client.patch(
        products_url(store, f"/{second['id']}/variants/{second['variants'][0]['id']}"),
        json={"sku": first["variants"][0]["sku"].upper()},
        headers=ALICE,
    )

    assert response.status_code == 409
    assert error_of(response) == "SKU is already in use"


@pytest.mark.parametrize(
    "body", [{}, {"price_minor": -1}, {"sku": " "}, {"stock": 1.5}]
)
async def test_update_variant_rejects_bad_input(
    client: AsyncClient, world: World, body: dict[str, Any]
) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")

    response = await client.patch(
        products_url(
            store, f"/{created['id']}/variants/{created['variants'][0]['id']}"
        ),
        json=body,
        headers=ALICE,
    )

    assert response.status_code == 422


async def test_variant_of_another_product_is_a_404(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    first = await create_product(client, store, "alice")
    second = await create_product(client, store, "alice")
    foreign_variant = second["variants"][0]["id"]

    patch = await client.patch(
        products_url(store, f"/{first['id']}/variants/{foreign_variant}"),
        json={"stock": 99},
        headers=ALICE,
    )
    delete = await client.delete(
        products_url(store, f"/{first['id']}/variants/{foreign_variant}"), headers=ALICE
    )

    assert {patch.status_code, delete.status_code} == {404}
    assert {error_of(patch), error_of(delete)} == {"Variant not found"}


async def test_delete_variant_keeps_at_least_one(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")
    first, second = created["variants"]

    removed = await client.delete(
        products_url(store, f"/{created['id']}/variants/{first['id']}"), headers=ALICE
    )
    last = await client.delete(
        products_url(store, f"/{created['id']}/variants/{second['id']}"), headers=ALICE
    )

    assert removed.status_code == 200
    assert [v["id"] for v in removed.json()["data"]["variants"]] == [second["id"]]
    assert last.status_code == 422
    assert error_of(last) == "A product needs at least one variant"


# --- images --------------------------------------------------------------------------


async def test_add_images_in_order_and_remove_one(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")
    keys = [f"stores/{store}/{unique()}.{ext}" for ext in ("jpg", "png", "webp")]

    for index, key in enumerate(keys):
        response = await client.post(
            products_url(store, f"/{created['id']}/images"),
            json={"storage_key": key, "alt_text": f"photo {index}"},
            headers=ALICE,
        )
        assert response.status_code == 201
    images = response.json()["data"]["images"]
    removed = await client.delete(
        products_url(store, f"/{created['id']}/images/{images[1]['id']}"), headers=ALICE
    )

    assert [i["storage_key"] for i in images] == keys
    assert [i["position"] for i in images] == [0, 1, 2]
    assert images[0]["alt_text"] == "photo 0"
    assert [i["storage_key"] for i in removed.json()["data"]["images"]] == [
        keys[0],
        keys[2],
    ]


async def test_an_image_key_can_be_attached_once(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    first = await create_product(client, store, "alice")
    second = await create_product(client, store, "alice")
    key = f"stores/{store}/{unique()}.png"
    await client.post(
        products_url(store, f"/{first['id']}/images"),
        json={"storage_key": key},
        headers=ALICE,
    )

    again = await client.post(
        products_url(store, f"/{first['id']}/images"),
        json={"storage_key": key},
        headers=ALICE,
    )
    elsewhere = await client.post(
        products_url(store, f"/{second['id']}/images"),
        json={"storage_key": key},
        headers=ALICE,
    )

    assert again.status_code == elsewhere.status_code == 409
    assert error_of(again) == "Image is already attached"
    assert_no_database_text(again)


async def test_alt_text_is_limited(client: AsyncClient, world: World) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")

    response = await client.post(
        products_url(store, f"/{created['id']}/images"),
        json={"storage_key": f"stores/{store}/{unique()}.png", "alt_text": "a" * 501},
        headers=ALICE,
    )

    assert response.status_code == 422


async def test_a_product_holds_at_most_twenty_images(
    client: AsyncClient, world: World
) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")
    path = products_url(store, f"/{created['id']}/images")
    for _ in range(20):
        ok = await client.post(
            path, json={"storage_key": f"stores/{store}/{unique()}.png"}, headers=ALICE
        )
        assert ok.status_code == 201

    over = await client.post(
        path, json={"storage_key": f"stores/{store}/{unique()}.png"}, headers=ALICE
    )

    assert over.status_code == 422


async def test_unknown_image_is_a_404(client: AsyncClient, world: World) -> None:
    store = north(world)
    created = await create_product(client, store, "alice")

    response = await client.delete(
        products_url(store, f"/{created['id']}/images/{unique()}"), headers=ALICE
    )

    assert response.status_code == 404
    assert error_of(response) == "Image not found"
