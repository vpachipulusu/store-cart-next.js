"""Product plan limit on create against real store databases (KAN-84).

The Free plan allows 25 products per store (``app.core.plans``). Runs only when
``TEST_DATABASE_URL`` points at a throwaway local server (see ``tests/isolation_world.py``).
"""



import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.plans import PLANS, PlanKey
from tests.api.products_support import (
    as_user,
    create_product,
    error_of,
    products_url,
    provisioned_world,
    simple_payload,
    store_of,
)
from tests.isolation_world import World, header_identity_app, make_client
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world() -> AsyncIterator[World]:
    async with provisioned_world(unlimited=False) as built:
        yield built


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client(world: World) -> AsyncIterator[AsyncClient]:
    async with make_client(header_identity_app(world)) as http:
        yield http


FREE_LIMIT = PLANS[PlanKey.FREE].max_products
assert FREE_LIMIT is not None
ALICE = as_user("alice")
BOB = as_user("bob")


async def fill(client: AsyncClient, store_id: str, user: str, count: int) -> list[str]:
    ids = []
    for _ in range(count):
        ids.append(
            (await create_product(client, store_id, user, simple_payload()))["id"]
        )
    return ids


async def post(client: AsyncClient, store_id: str, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    return await client.post(
        products_url(store_id), json=simple_payload(), headers=headers
    )


async def total(client: AsyncClient, store_id: str, headers: dict[str, str]) -> int:
    response = await client.get(products_url(store_id), headers=headers)
    assert response.status_code == 200
    return int(response.json()["total"])


async def test_create_over_the_plan_limit_is_refused_with_an_upgrade_message(
    client: AsyncClient, world: World
) -> None:
    store_id = store_of(world, "a", "north")
    ids = await fill(client, store_id, "alice", FREE_LIMIT)

    refused = await post(client, store_id, ALICE)

    assert refused.status_code == 409
    assert "Free plan allows 25 products" in error_of(refused)
    assert "Upgrade" in error_of(refused)
    assert refused.headers["cache-control"] == "no-store"
    assert await total(client, store_id, ALICE) == FREE_LIMIT
    # Reads and edits are not blocked at the limit; deleting frees a slot.
    patched = await client.patch(
        products_url(store_id, f"/{ids[0]}"), json={"status": "active"}, headers=ALICE
    )
    assert patched.status_code == 200
    deleted = await client.delete(products_url(store_id, f"/{ids[1]}"), headers=ALICE)
    assert deleted.status_code == 204
    assert (await post(client, store_id, ALICE)).status_code == 201
    assert (await post(client, store_id, ALICE)).status_code == 409


async def test_concurrent_creates_cannot_exceed_the_limit(
    client: AsyncClient, world: World
) -> None:
    store_id = store_of(world, "a", "south")
    await fill(client, store_id, "alice", FREE_LIMIT - 1)

    responses = await asyncio.gather(*(post(client, store_id, ALICE) for _ in range(6)))

    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409, 409, 409]
    assert await total(client, store_id, ALICE) == FREE_LIMIT


async def test_upgrading_the_plan_lifts_the_limit(
    client: AsyncClient, world: World
) -> None:
    store_id = store_of(world, "b", "north")
    await fill(client, store_id, "bob", FREE_LIMIT)
    assert (await post(client, store_id, BOB)).status_code == 409
    # The count is per store: a sibling store of the same organisation has room.
    sibling = store_of(world, "b", "east")
    assert (await post(client, sibling, BOB)).status_code == 201

    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE organizations SET subscription_tier = 'pro' WHERE id = :id"),
            {"id": world.tenant("b").org_id},
        )

    assert (await post(client, store_id, BOB)).status_code == 201
    assert await total(client, store_id, BOB) == FREE_LIMIT + 1


async def test_enterprise_has_no_product_limit(
    client: AsyncClient, world: World
) -> None:
    store_id = store_of(world, "b", "south")
    async with world.platform.begin() as connection:
        await connection.execute(
            text(
                "UPDATE organizations SET subscription_tier = 'enterprise' "
                "WHERE id = :id"
            ),
            {"id": world.tenant("b").org_id},
        )
    await fill(client, store_id, "bob", FREE_LIMIT + 1)

    assert await total(client, store_id, BOB) == FREE_LIMIT + 1


async def test_admin_grant_lifts_the_limit_only_while_unexpired(
    client: AsyncClient, world: World
) -> None:
    store_id = store_of(world, "a", "north")
    assert (await post(client, store_id, ALICE)).status_code == 409

    async def grant(until: str) -> None:
        async with world.platform.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE organizations SET granted_plan = 'pro', "
                    f"granted_until = {until} WHERE id = :id"
                ),
                {"id": world.tenant("a").org_id},
            )

    await grant("now() + interval '1 day'")
    assert (await post(client, store_id, ALICE)).status_code == 201

    await grant("now() - interval '1 day'")
    assert (await post(client, store_id, ALICE)).status_code == 409
