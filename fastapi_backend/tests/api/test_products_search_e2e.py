"""Product list text search and the categories list against real store databases (KAN-246).

Search matches title or any variant SKU, ignoring case, with LIKE wildcards taken literally,
and combines with the status and category filters. The categories list is read-only,
ordered, and scoped to the caller's own store. Runs only when ``TEST_DATABASE_URL`` points
at a throwaway local server (see ``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from typing import Any
from urllib.parse import quote

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.ids import new_id
from app.services.store_sessions import open_store_session
from tests.api.products_support import (  # noqa: F401  (fixtures)
    add_category,
    as_user,
    assert_no_database_text,
    client,
    create_product,
    error_of,
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


def south(world: World) -> str:
    return store_of(world, "a", "south")


def north(world: World) -> str:
    return store_of(world, "a", "north")


async def search(
    client: AsyncClient, store: str, q: str, extra: str = ""
) -> dict[str, Any]:
    response = await client.get(
        products_url(store, f"?q={quote(q)}{extra}"), headers=ALICE
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def ids_of(body: dict[str, Any]) -> set[str]:
    return {row["id"] for row in body["data"]}


async def named(
    client: AsyncClient, store: str, title: str, sku: str, **over: Any
) -> str:
    created = await create_product(
        client,
        store,
        "alice",
        simple_payload(
            title=title, slug=f"s-{unique()}", variants=[variant_payload(sku)], **over
        ),
    )
    return str(created["id"])


# --- search --------------------------------------------------------------------------


async def test_search_matches_title_ignoring_case(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    hit = await named(client, south(world), f"Blue Mug {tag}", f"T-{unique()}")
    await named(client, south(world), f"Red Plate {unique()}", f"T-{unique()}")

    body = await search(client, south(world), f"bLuE mUg {tag.upper()}")

    assert ids_of(body) == {hit}
    assert body["total"] == 1


async def test_search_matches_a_variant_sku_ignoring_case(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    hit = await named(client, south(world), f"Plain {unique()}", f"Sku-{tag}")

    body = await search(client, south(world), f"SKU-{tag.upper()}")

    assert ids_of(body) == {hit}


async def test_search_matches_any_variant_of_the_product(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    created = await create_product(
        client,
        south(world),
        "alice",
        {
            "title": f"Shirt {unique()}",
            "slug": f"shirt-{unique()}",
            "options": [{"name": "Size", "values": ["S", "M"]}],
            "variants": [
                variant_payload(f"A-{unique()}", options={"Size": "S"}),
                variant_payload(f"B-{tag}", options={"Size": "M"}),
            ],
        },
    )

    body = await search(client, south(world), f"b-{tag}")

    assert ids_of(body) == {created["id"]}
    assert body["data"][0]["variant_count"] == 2


async def test_search_is_trimmed_and_blank_means_no_search(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    hit = await named(client, south(world), f"Trim {tag}", f"T-{unique()}")

    trimmed = await search(client, south(world), f"   trim {tag}  ")
    blank = await search(client, south(world), "   ")
    unfiltered = await client.get(products_url(south(world)), headers=ALICE)

    assert ids_of(trimmed) == {hit}
    assert blank["total"] == unfiltered.json()["total"]


@pytest.mark.parametrize(
    ("wildcard", "decoy"),
    [("%", "100x"), ("_", "ab"), ("\\", "ab"), ("a%b", "axb"), ("a_b", "axb")],
)
async def test_search_takes_like_wildcards_literally(
    client: AsyncClient, world: World, wildcard: str, decoy: str
) -> None:
    tag = unique()
    literal = f"zq{tag}{wildcard}"
    hit = await named(client, south(world), f"Item {literal} end", f"T-{unique()}")
    await named(client, south(world), f"Item zq{tag}{decoy} end", f"T-{unique()}")

    body = await search(client, south(world), literal)

    assert ids_of(body) == {hit}


async def test_search_combines_with_status_and_category(
    client: AsyncClient, world: World
) -> None:
    store = south(world)
    tag = unique()
    category = await add_category(world, store)
    both = await named(
        client,
        store,
        f"Combo {tag} a",
        f"T-{unique()}",
        status="active",
        category_ids=[category],
    )
    await named(
        client, store, f"Combo {tag} b", f"T-{unique()}", category_ids=[category]
    )
    await named(client, store, f"Combo {tag} c", f"T-{unique()}", status="active")

    by_text = await search(client, store, f"combo {tag}")
    with_status = await search(client, store, f"combo {tag}", "&status=active")
    with_both = await search(
        client, store, f"combo {tag}", f"&status=active&category_id={category}"
    )

    assert by_text["total"] == 3
    assert with_status["total"] == 2
    assert ids_of(with_both) == {both}
    assert with_both["total"] == 1


async def test_search_pagination_is_unchanged(
    client: AsyncClient, world: World
) -> None:
    store = south(world)
    tag = unique()
    for index in range(3):
        await named(client, store, f"Page {tag} {index}", f"T-{unique()}")

    first = await search(client, store, f"page {tag}", "&limit=2")
    second = await search(client, store, f"page {tag}", "&limit=2&offset=2")

    assert first["total"] == second["total"] == 3
    assert (len(first["data"]), len(second["data"])) == (2, 1)
    assert ids_of(first).isdisjoint(ids_of(second))


async def test_search_does_not_cross_stores(client: AsyncClient, world: World) -> None:
    tag = unique()
    await named(client, north(world), f"Secret {tag}", f"T-{unique()}")

    other_store = await search(client, south(world), f"secret {tag}")

    assert other_store["data"] == []
    assert other_store["total"] == 0


async def test_search_accepts_100_characters_and_rejects_101(
    client: AsyncClient, world: World
) -> None:
    store = south(world)

    ok = await client.get(products_url(store, f"?q={'x' * 100}"), headers=ALICE)
    padded = await client.get(
        products_url(store, f"?q=%20{'x' * 100}%20"), headers=ALICE
    )
    too_long = await client.get(products_url(store, f"?q={'x' * 101}"), headers=ALICE)
    huge = await client.get(products_url(store, f"?q={'x' * 5000}"), headers=ALICE)
    nul = await client.get(products_url(store, "?q=a%00b"), headers=ALICE)

    assert (ok.status_code, padded.status_code) == (200, 200)
    assert too_long.status_code == huge.status_code == nul.status_code == 422
    assert_no_database_text(too_long)
    assert too_long.json() == huge.json() == nul.json()


async def test_search_text_is_not_executed_as_sql(
    client: AsyncClient, world: World
) -> None:
    body = await search(client, south(world), "'; DROP TABLE products; --")

    assert body["data"] == []
    still_there = await client.get(products_url(south(world)), headers=ALICE)
    assert still_there.status_code == 200


# --- categories ----------------------------------------------------------------------


def categories_url(store_id: str) -> str:
    return f"/v1/stores/{store_id}/categories"


async def seed_tree(world: World, store_id: str, tag: str) -> dict[str, str]:
    ids = {name: new_id() for name in ("shoes", "boots", "hats", "sandals")}
    rows = [
        (ids["hats"], "Hats", f"hats-{tag}", None, 1),
        (ids["shoes"], "Shoes", f"shoes-{tag}", None, 0),
        (ids["sandals"], "Sandals", f"sandals-{tag}", ids["shoes"], 1),
        (ids["boots"], "Boots", f"boots-{tag}", ids["shoes"], 0),
    ]
    async with open_store_session(store_id, world.provider) as session:
        for row_id, name, slug, parent, position in rows:
            await session.execute(
                text(
                    "INSERT INTO categories (id, name, slug, parent_id, position) "
                    "VALUES (:i, :n, :s, :p, :o)"
                ),
                {"i": row_id, "n": name, "s": slug, "p": parent, "o": position},
            )
        await session.commit()
    return ids


async def test_categories_list_has_fields_and_stable_order(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    ids = await seed_tree(world, south(world), tag)

    response = await client.get(categories_url(south(world)), headers=ALICE)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    mine = [c for c in response.json()["data"] if c["slug"].endswith(tag)]
    assert [c["id"] for c in mine] == [
        ids["shoes"],
        ids["hats"],
        ids["boots"],
        ids["sandals"],
    ]
    assert mine[2] == {
        "id": ids["boots"],
        "name": "Boots",
        "slug": f"boots-{tag}",
        "parent_id": ids["shoes"],
        "position": 0,
    }
    assert response.json()["truncated"] is False


async def test_categories_are_scoped_to_the_resolved_store(
    client: AsyncClient, world: World
) -> None:
    tag = unique()
    await seed_tree(world, south(world), tag)

    sibling = await client.get(categories_url(north(world)), headers=ALICE)
    foreign = await client.get(
        categories_url(store_of(world, "b", "north")), headers=ALICE
    )
    missing = await client.get(categories_url(unique()), headers=ALICE)

    assert not [c for c in sibling.json()["data"] if c["slug"].endswith(tag)]
    assert foreign.status_code == missing.status_code == 404
    assert error_of(foreign) == error_of(missing)
    assert_no_database_text(foreign)


async def test_categories_can_be_read_by_staff_and_have_no_write_route(
    client: AsyncClient, world: World
) -> None:
    read = await client.get(categories_url(south(world)), headers=as_user("amy"))
    write = await client.post(categories_url(south(world)), json={}, headers=ALICE)

    assert read.status_code == 200
    assert write.status_code == 405


async def test_categories_need_a_session(client: AsyncClient, world: World) -> None:
    anonymous = await client.get(categories_url(south(world)))

    assert anonymous.status_code in {401, 403}
