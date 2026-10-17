"""Shared fixtures and helpers for the product API suites (KAN-245).

One world per test module (two organisations, three stores each, see
``tests/isolation_world.py``) with five stores on real Postgres databases migrated to the
store head. Tests create their own products with unique slugs and SKUs, so they never
depend on what another test left behind; the listing tests use a store no other test writes
to. ``a.east`` stays unprovisioned (no database) for the 503 test.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.core.ids import new_id
from app.services.store_migrations import migrate_store
from app.services.store_sessions import open_store_session
from tests.isolation_world import (
    World,
    header_identity_app,
    make_client,
    open_world,
)

PROVISIONED = (
    ("a", "north"),
    ("a", "south"),
    ("b", "north"),
    ("b", "south"),
    ("b", "east"),
)
LISTING_STORE = ("b", "south")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world() -> AsyncIterator[World]:
    with pytest.MonkeyPatch.context() as patch:
        async with open_world(patch) as built:
            for label, slug in PROVISIONED:
                store_id = built.tenant(label).stores[slug]
                await built.provision(store_id)
                await migrate_store(store_id, built.provider)
            yield built


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client(world: World) -> AsyncIterator[AsyncClient]:
    async with make_client(header_identity_app(world)) as http:
        yield http


def store_of(world: World, label: str, slug: str) -> str:
    return world.tenant(label).stores[slug]


def products_url(store_id: str, suffix: str = "") -> str:
    return f"/v1/stores/{store_id}/products{suffix}"


def unique() -> str:
    return new_id()[:10].lower()


def variant_payload(tag: str, **over: Any) -> dict[str, Any]:
    return {"sku": f"SKU-{tag}", "price_minor": 1999, "stock": 5, **over}


def product_payload(**over: Any) -> dict[str, Any]:
    """A product with a Size option (S, M) and one variant per size."""
    tag = unique()
    payload: dict[str, Any] = {
        "title": f"Tee {tag}",
        "slug": f"tee-{tag}",
        "description": "Soft cotton",
        "options": [{"name": "Size", "values": ["S", "M"]}],
        "variants": [
            variant_payload(f"{tag}-S", options={"Size": "S"}),
            variant_payload(f"{tag}-M", price_minor=2199, options={"Size": "M"}),
        ],
    }
    return {**payload, **over}


def simple_payload(**over: Any) -> dict[str, Any]:
    """A product without options and a single variant."""
    tag = unique()
    return {
        "title": f"Mug {tag}",
        "slug": f"mug-{tag}",
        "variants": [variant_payload(tag)],
        **over,
    }


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}"}


async def create_product(
    client: AsyncClient,
    store_id: str,
    user: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        products_url(store_id),
        json=payload if payload is not None else product_payload(),
        headers=as_user(user),
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


def error_of(response: Response) -> str:
    error: str = response.json()["error"]
    return error


def assert_no_database_text(response: Response) -> None:
    body = response.text.lower()
    for leaked in (
        "constraint",
        "duplicate key",
        "uq_",
        "ck_",
        "sqlalchemy",
        "asyncpg",
        "postgres",
    ):
        assert leaked not in body, f"{leaked!r} leaked: {response.text}"


async def add_category(world: World, store_id: str) -> str:
    category_id = new_id()
    async with open_store_session(store_id, world.provider) as session:
        await session.execute(
            text("INSERT INTO categories (id, name, slug) VALUES (:i, 'Cat', :s)"),
            {"i": category_id, "s": f"cat-{category_id[:8].lower()}"},
        )
        await session.commit()
    return category_id


async def store_count(world: World, store_id: str, sql: str) -> int:
    return int(await world.store_value(store_id, sql))
