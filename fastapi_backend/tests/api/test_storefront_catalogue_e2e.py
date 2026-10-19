"""Public storefront catalogue against real store databases (KAN-75).

Only published products of an ACTIVE store are visible, drafts read like unknown slugs,
categories filter by slug, search matches titles, the bodies carry no SKU, stock count or
product ids, and one store's slugs mean nothing in another. Runs only when
``TEST_DATABASE_URL`` points at a throwaway local server (see ``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.core.config import settings
from app.core.ids import new_id
from app.services.store_sessions import open_store_session
from tests.api.products_support import (  # noqa: F401  (fixtures)
    assert_no_database_text,
    client,
    create_product,
    product_payload,
    simple_payload,
    store_of,
    unique,
    world,
)
from tests.isolation_world import World
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

NORTH = ("a", "north")
SOUTH_B = ("b", "south")
IMAGE_BASE = "https://img.example.test"


@pytest.fixture(autouse=True)
def image_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", IMAGE_BASE)


def url(slug: str, suffix: str) -> str:
    return f"/v1/storefront/{slug}{suffix}"


def data_of(response: Response) -> Any:
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def publish(
    client: AsyncClient,
    world: World,
    *,
    store: tuple[str, str] = NORTH,
    owner: str = "alice",
) -> dict[str, Any]:
    return await create_product(
        client, store_of(world, *store), owner, product_payload(status="active")
    )


async def run_sql(world: World, sql: str, **params: Any) -> None:
    async with open_store_session(store_of(world, *NORTH), world.provider) as session:
        await session.execute(text(sql), params)
        await session.commit()


async def add_category(world: World, parent_id: str | None = None) -> tuple[str, str]:
    category_id, slug = new_id(), f"cat-{unique()}"
    await run_sql(
        world,
        "INSERT INTO categories (id, name, slug, parent_id) VALUES (:i, :n, :s, :p)",
        i=category_id,
        n=slug.title(),
        s=slug,
        p=parent_id,
    )
    return category_id, slug


async def add_image(
    world: World, product_id: str, position: int, alt: str | None
) -> str:
    key = f"stores/{store_of(world, *NORTH)}/{new_id()}.jpg"
    await run_sql(
        world,
        "INSERT INTO product_images (id, product_id, storage_key, alt_text, position) "
        "VALUES (:i, :p, :k, :a, :n)",
        i=new_id(),
        p=product_id,
        k=key,
        a=alt,
        n=position,
    )
    return key


async def test_a_published_product_reads_with_public_fields_only(
    client: AsyncClient, world: World
) -> None:
    product = await publish(client, world)
    key = await add_image(world, product["id"], 0, "Front")

    data = data_of(await client.get(url("a-north", f"/products/{product['slug']}")))

    assert data["title"] == product["title"]
    assert data["images"] == [{"url": f"{IMAGE_BASE}/{key}", "alt_text": "Front"}]
    assert [o["name"] for o in data["options"]] == ["Size"]
    assert {v["id"] for v in data["variants"]} == {v["id"] for v in product["variants"]}
    assert all(v["in_stock"] is True for v in data["variants"])
    assert set(data["variants"][0]) == {
        "id",
        "price_minor",
        "compare_at_price_minor",
        "in_stock",
        "option_value_ids",
    }
    body = str(data)
    assert product["id"] not in body
    assert product["variants"][0]["sku"] not in body


async def test_a_draft_is_the_same_404_as_an_unknown_slug(
    client: AsyncClient, world: World
) -> None:
    draft = await create_product(
        client, store_of(world, *NORTH), "alice", simple_payload(status="draft")
    )

    hidden = await client.get(url("a-north", f"/products/{draft['slug']}"))
    unknown = await client.get(url("a-north", "/products/no-such-product"))
    listing = data_of(
        await client.get(url("a-north", "/products"), params={"q": draft["title"]})
    )

    assert hidden.status_code == unknown.status_code == 404
    assert (
        hidden.json()
        == unknown.json()
        == {
            "success": False,
            "error": "Product not found",
        }
    )
    assert listing == []


async def test_the_listing_filters_by_category_slug_and_searches_titles(
    client: AsyncClient, world: World
) -> None:
    parent_id, parent_slug = await add_category(world)
    child_id, child_slug = await add_category(world, parent_id)
    in_category = await publish(client, world)
    elsewhere = await publish(client, world)
    await run_sql(
        world,
        "INSERT INTO product_categories (product_id, category_id) VALUES (:p, :c)",
        p=in_category["id"],
        c=child_id,
    )
    await add_image(world, in_category["id"], 1, "Second")
    first_key = await add_image(world, in_category["id"], 0, "First")

    by_category = await client.get(
        url("a-north", "/products"), params={"category": child_slug}
    )
    by_search = data_of(
        await client.get(url("a-north", "/products"), params={"q": elsewhere["title"]})
    )
    categories = data_of(await client.get(url("a-north", "/categories")))

    assert by_category.status_code == 200
    body = by_category.json()
    assert [p["slug"] for p in body["data"]] == [in_category["slug"]]
    assert body["total"] == 1
    assert body["data"][0]["image"] == {
        "url": f"{IMAGE_BASE}/{first_key}",
        "alt_text": "First",
    }
    assert [p["slug"] for p in by_search] == [elsewhere["slug"]]
    by_sku = await client.get(
        url("a-north", "/products"), params={"q": elsewhere["variants"][0]["sku"]}
    )
    assert data_of(by_sku) == []
    assert {
        "name": child_slug.title(),
        "slug": child_slug,
        "parent_slug": parent_slug,
    } in categories


async def test_an_unknown_category_is_a_404(client: AsyncClient) -> None:
    response = await client.get(
        url("a-north", "/products"), params={"category": "no-such-category"}
    )

    assert response.status_code == 404
    assert response.json()["error"] == "Category not found"


async def test_a_store_does_not_see_another_stores_products(
    client: AsyncClient, world: World
) -> None:
    other = await publish(client, world, store=SOUTH_B, owner="bob")

    response = await client.get(url("a-north", f"/products/{other['slug']}"))

    assert response.status_code == 404
    assert_no_database_text(response)


async def test_a_store_that_is_not_active_is_not_found(
    client: AsyncClient, world: World
) -> None:
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = 'SUSPENDED' WHERE id = :i"),
            {"i": store_of(world, "a", "south")},
        )

    for suffix in ("/products", "/categories", "/products/anything"):
        response = await client.get(url("a-south", suffix))
        assert response.status_code == 404, suffix
        assert response.json() == {"success": False, "error": "Store not found"}
