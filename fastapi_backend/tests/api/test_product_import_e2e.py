"""Product CSV import through the real app on real store databases (KAN-74).

Valid and invalid files, the byte cap, tenant isolation (another organisation's store, a
sibling store, SKUs of other stores) and roles. Runs only when ``TEST_DATABASE_URL`` points
at a throwaway local server (see ``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.api.v1.product_import import MAX_REQUEST_BYTES
from app.services.product_import import COLUMNS
from tests.api.products_support import (  # noqa: F401  (fixtures)
    as_user,
    assert_no_database_text,
    client,
    create_product,
    error_of,
    products_url,
    simple_payload,
    store_count,
    store_of,
    unique,
    world,
)
from tests.isolation_world import World, same_failure
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

HEADER = ",".join(COLUMNS)


def csv_rows(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode()


def product_row(tag: str, **over: str) -> str:
    cells = {
        "title": f"Lamp {tag}",
        "slug": "",
        "description": "Brass",
        "status": "active",
        "sku": f"LAMP-{tag}",
        "price_minor": "4500",
        "compare_at_price_minor": "",
        "weight_grams": "900",
        "stock": "3",
        **over,
    }
    return ",".join(cells[c] for c in COLUMNS)


async def upload(
    client: AsyncClient, store_id: str, content: bytes, user: str = "alice"
) -> Response:
    return await client.post(
        products_url(store_id, "/import"),
        files={"file": ("products.csv", content, "text/csv")},
        headers=as_user(user),
    )


async def products_in(world: World, store_id: str) -> int:
    return await store_count(world, store_id, "SELECT count(*) FROM products")


def body_of(response: Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def set_tier(world: World, organization_id: str, tier: str) -> None:
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE organizations SET subscription_tier = :t WHERE id = :i"),
            {"t": tier, "i": organization_id},
        )


async def test_a_valid_file_creates_every_product(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    first, second = unique(), unique()

    response = await upload(
        client, store, csv_rows(product_row(first), product_row(second, status=""))
    )

    body = body_of(response)
    assert response.headers["cache-control"] == "no-store"
    assert body["imported"] == 2
    assert body["errors"] == []
    assert body["truncated"] is False
    read = await client.get(
        products_url(store, f"/{body['product_ids'][0]}"), headers=as_user("alice")
    )
    product = read.json()["data"]
    assert (product["title"], product["slug"], product["status"]) == (
        f"Lamp {first}",
        f"lamp-{first}",
        "active",
    )
    variant = product["variants"][0]
    assert (variant["sku"], variant["price_minor"], variant["stock"]) == (
        f"LAMP-{first}",
        4500,
        3,
    )
    second_read = await client.get(
        products_url(store, f"/{body['product_ids'][1]}"), headers=as_user("alice")
    )
    assert second_read.json()["data"]["status"] == "draft"


async def test_one_bad_row_writes_nothing_and_reports_row_and_column(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    before = await products_in(world, store)

    response = await upload(
        client,
        store,
        csv_rows(
            product_row(unique()),
            product_row(unique(), price_minor="12.50"),
            product_row(unique(), title="=cmd|' /C calc'!A0"),
        ),
    )

    body = body_of(response)
    assert body["imported"] == 0
    assert body["product_ids"] == []
    assert [(e["row"], e["column"]) for e in body["errors"]] == [
        (3, "price_minor"),
        (4, "title"),
    ]
    assert await products_in(world, store) == before


async def test_a_sku_already_in_the_store_is_a_row_error(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    existing = await create_product(client, store, "alice", simple_payload())
    taken_sku = existing["variants"][0]["sku"]
    before = await products_in(world, store)

    response = await upload(
        client,
        store,
        csv_rows(product_row(unique()), product_row(unique(), sku=taken_sku.lower())),
    )

    body = body_of(response)
    assert body["errors"] == [
        {"row": 3, "column": "sku", "message": "SKU is already in use"}
    ]
    assert await products_in(world, store) == before
    assert_no_database_text(response)


async def test_skus_and_slugs_of_another_store_do_not_conflict(
    client: AsyncClient, world: World
) -> None:
    other = await create_product(
        client, store_of(world, "b", "north"), "bob", simple_payload()
    )
    store = store_of(world, "a", "north")

    response = await upload(
        client,
        store,
        csv_rows(
            product_row(unique(), slug=other["slug"], sku=other["variants"][0]["sku"])
        ),
    )

    assert body_of(response)["imported"] == 1


async def test_another_organisations_store_answers_like_a_missing_store(
    client: AsyncClient, world: World
) -> None:
    victim = store_of(world, "b", "north")
    before = await products_in(world, victim)
    content = csv_rows(product_row(unique()))

    foreign = await upload(client, victim, content)
    missing = await upload(client, unique(), content)

    same_failure(foreign, missing)
    assert foreign.status_code == 404
    assert error_of(foreign) == "Store not found"
    assert await products_in(world, victim) == before


async def test_the_import_lands_only_in_the_store_in_the_path(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "south")
    sibling = store_of(world, "a", "north")
    before = await products_in(world, sibling)

    response = await upload(client, store, csv_rows(product_row(unique())))

    assert body_of(response)["imported"] == 1
    assert await products_in(world, sibling) == before


@pytest.mark.parametrize(("user", "status"), [("amy", 403), ("eve", 404)])
async def test_staff_and_outsiders_cannot_import(
    client: AsyncClient, world: World, user: str, status: int
) -> None:
    store = store_of(world, "a", "north")
    before = await products_in(world, store)

    response = await upload(client, store, csv_rows(product_row(unique())), user)

    assert response.status_code == status
    assert await products_in(world, store) == before


async def test_an_admin_can_import(client: AsyncClient, world: World) -> None:
    response = await upload(
        client, store_of(world, "a", "north"), csv_rows(product_row(unique())), "dana"
    )

    assert body_of(response)["imported"] == 1


async def test_no_session_is_401(client: AsyncClient, world: World) -> None:
    response = await client.post(
        products_url(store_of(world, "a", "north"), "/import"),
        files={"file": ("p.csv", csv_rows(product_row(unique())), "text/csv")},
    )

    assert response.status_code == 401


async def test_an_oversized_upload_is_refused(
    client: AsyncClient, world: World
) -> None:
    response = await upload(
        client, store_of(world, "a", "north"), b"x" * (MAX_REQUEST_BYTES + 1)
    )

    assert response.status_code == 413
    assert "larger than" in error_of(response)


async def test_a_body_without_a_file_part_is_400(
    client: AsyncClient, world: World
) -> None:
    url = products_url(store_of(world, "a", "north"), "/import")

    other_part = await client.post(
        url, files={"other": ("a.csv", b"b", "text/csv")}, headers=as_user("alice")
    )
    not_multipart = await client.post(
        url, content=csv_rows(product_row(unique())), headers=as_user("alice")
    )

    extra_field = await client.post(
        url,
        data={"note": "x"},
        files={"file": ("p.csv", csv_rows(product_row(unique())), "text/csv")},
        headers=as_user("alice"),
    )

    assert other_part.status_code == 400
    assert extra_field.status_code == 400
    assert not_multipart.status_code == 400
    assert error_of(not_multipart) == "Attach the CSV file as the file field"


async def test_a_file_over_the_plan_limit_is_refused_whole(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    org_id = world.tenant("a").org_id
    await set_tier(world, org_id, "free")
    try:
        before = await products_in(world, store)
        rows = [product_row(unique()) for _ in range(30)]

        response = await upload(client, store, csv_rows(*rows))
    finally:
        await set_tier(world, org_id, "enterprise")

    body = body_of(response)
    assert body["imported"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] is None
    assert "Upgrade" in body["errors"][0]["message"]
    assert await products_in(world, store) == before
