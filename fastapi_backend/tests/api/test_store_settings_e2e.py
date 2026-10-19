"""Store settings routes (shipping and tax) against real store databases (KAN-82, KAN-83).

Defaults, partial updates, validation, roles, tenant isolation and the 503, plus the
server-side totals computed from the saved settings. Runs only when ``TEST_DATABASE_URL``
points at a throwaway local server (see ``tests/isolation_world.py``).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.repositories.store_settings import StoreSettingsRepository
from app.services.store_sessions import open_store_session
from app.services.store_settings import StoreSettingsService
from app.services.store_totals import LineAmount, compute_totals
from tests.api.products_support import (  # noqa: F401  (fixtures)
    as_user,
    assert_no_database_text,
    client,
    error_of,
    store_of,
    world,
)
from tests.isolation_world import World
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

ALICE = as_user("alice")  # OWNER of organisation a
DANA = as_user("dana")  # ADMIN of a
AMY = as_user("amy")  # STAFF of a
BOB = as_user("bob")  # OWNER of b
DEFAULTS = {
    "shipping_flat_rate_minor": 0,
    "free_shipping_threshold_minor": None,
    "tax_rate_bps": 0,
    "prices_include_tax": False,
}


def url(store_id: str) -> str:
    return f"/v1/stores/{store_id}/store-settings"


def values(response: Any) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    return {key: body[key] for key in DEFAULTS}


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def reset_north(client: AsyncClient, world: World) -> AsyncIterator[None]:
    """Every test starts and ends on defaults, even when it fails half way."""
    store = store_of(world, "a", "north")
    await reset(client, store)
    yield
    await reset(client, store)


async def reset(client: AsyncClient, store_id: str) -> None:
    response = await client.patch(url(store_id), json={**DEFAULTS}, headers=ALICE)
    assert response.status_code == 200


async def test_a_new_store_has_no_shipping_and_no_tax(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(url(store_of(world, "b", "north")), headers=BOB)

    assert response.status_code == 200
    assert values(response) == DEFAULTS
    assert response.headers["cache-control"] == "no-store"


async def test_saves_shipping_and_tax_and_reads_them_back(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    body = {
        "shipping_flat_rate_minor": 499,
        "free_shipping_threshold_minor": 5000,
        "tax_rate_bps": 2000,
        "prices_include_tax": True,
    }

    saved = await client.patch(url(store), json=body, headers=ALICE)
    read = await client.get(url(store), headers=AMY)

    assert saved.status_code == 200
    assert values(saved) == body == values(read)
    await reset(client, store)


async def test_a_partial_update_leaves_the_other_fields(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    await client.patch(
        url(store),
        json={"shipping_flat_rate_minor": 300, "tax_rate_bps": 500},
        headers=ALICE,
    )

    response = await client.patch(url(store), json={"tax_rate_bps": 700}, headers=DANA)

    assert values(response)["shipping_flat_rate_minor"] == 300
    assert values(response)["tax_rate_bps"] == 700
    await reset(client, store)


async def test_null_threshold_removes_it_and_an_empty_patch_changes_nothing(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    await client.patch(
        url(store), json={"free_shipping_threshold_minor": 4000}, headers=ALICE
    )

    empty = await client.patch(url(store), json={}, headers=ALICE)
    cleared = await client.patch(
        url(store), json={"free_shipping_threshold_minor": None}, headers=ALICE
    )

    assert values(empty)["free_shipping_threshold_minor"] == 4000
    assert values(cleared)["free_shipping_threshold_minor"] is None
    await reset(client, store)


@pytest.mark.parametrize(
    "body",
    [
        {"shipping_flat_rate_minor": -1},
        {"shipping_flat_rate_minor": 100_000_000_001},
        {"shipping_flat_rate_minor": 4.5},
        {"shipping_flat_rate_minor": True},
        {"shipping_flat_rate_minor": "499"},
        {"free_shipping_threshold_minor": 0},
        {"tax_rate_bps": -1},
        {"tax_rate_bps": 10_001},
        {"prices_include_tax": "yes"},
        {"currency": "USD"},
    ],
)
async def test_invalid_input_is_a_422_and_changes_nothing(
    client: AsyncClient, world: World, body: dict[str, Any]
) -> None:
    store = store_of(world, "a", "north")

    response = await client.patch(url(store), json=body, headers=ALICE)
    read = await client.get(url(store), headers=ALICE)

    assert response.status_code == 422
    assert_no_database_text(response)
    assert values(read) == DEFAULTS


async def test_staff_can_read_but_not_change(client: AsyncClient, world: World) -> None:
    store = store_of(world, "a", "north")

    read = await client.get(url(store), headers=AMY)
    write = await client.patch(url(store), json={"tax_rate_bps": 1}, headers=AMY)

    assert (read.status_code, write.status_code) == (200, 403)
    assert error_of(write) == "Forbidden"


async def test_another_organisation_gets_the_same_404_as_an_unknown_store(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")

    foreign = await client.get(url(store), headers=BOB)
    unknown = await client.get(url("does-not-exist"), headers=BOB)
    write = await client.patch(url(store), json={"tax_rate_bps": 1}, headers=BOB)

    assert (foreign.status_code, write.status_code) == (404, 404)
    assert foreign.json() == unknown.json()


async def test_settings_belong_to_one_store(client: AsyncClient, world: World) -> None:
    north, south = store_of(world, "a", "north"), store_of(world, "a", "south")

    await client.patch(url(north), json={"tax_rate_bps": 1500}, headers=ALICE)
    other = await client.get(url(south), headers=ALICE)

    assert values(other) == DEFAULTS
    await reset(client, north)


async def test_a_store_without_a_database_answers_a_fixed_503(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "east")  # never provisioned

    response = await client.get(url(store), headers=ALICE)

    assert response.status_code == 503
    assert error_of(response) == "Store database is not available"
    assert_no_database_text(response)


async def test_totals_use_the_saved_shipping_and_tax(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    await client.patch(
        url(store),
        json={
            "shipping_flat_rate_minor": 499,
            "free_shipping_threshold_minor": 5000,
            "tax_rate_bps": 2000,
        },
        headers=ALICE,
    )

    async with open_store_session(store, world.provider) as session:
        settings = await StoreSettingsService(
            StoreSettingsRepository(session), session
        ).totals_settings()
    below = compute_totals([LineAmount(2000, 2)], settings)
    free = compute_totals([LineAmount(2500, 2)], settings)

    assert (below.shipping_minor, below.tax_minor, below.total_minor) == (
        499,
        800,
        5299,
    )
    assert (free.shipping_minor, free.tax_minor, free.total_minor) == (0, 1000, 6000)
    await reset(client, store)


@pytest.mark.parametrize(
    "body",
    [
        {"tax_rate_bps": None},
        {"shipping_flat_rate_minor": None},
        {"prices_include_tax": None},
    ],
)
async def test_an_explicit_null_on_a_required_field_is_a_422(
    client: AsyncClient, world: World, body: dict[str, Any]
) -> None:
    response = await client.patch(
        url(store_of(world, "a", "north")), json=body, headers=ALICE
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


async def test_updated_at_moves_only_on_a_real_change(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    before = (await client.get(url(store), headers=ALICE)).json()["updated_at"]

    await client.patch(url(store), json={}, headers=ALICE)
    same = (await client.get(url(store), headers=ALICE)).json()["updated_at"]
    await client.patch(url(store), json={"tax_rate_bps": 100}, headers=ALICE)
    after = (await client.get(url(store), headers=ALICE)).json()["updated_at"]

    assert same == before and after != before


async def test_requests_without_a_session_or_internal_key_are_refused(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")

    no_session = await client.get(url(store))
    no_key = await client.get(url(store), headers={**ALICE, "X-Internal-Key": "wrong"})

    assert no_session.status_code == 401
    assert no_key.status_code in (401, 403)


async def test_a_deleted_settings_row_is_recreated_on_the_next_change(
    client: AsyncClient, world: World
) -> None:
    store = store_of(world, "a", "north")
    async with open_store_session(store, world.provider) as session:
        await session.execute(text("DELETE FROM store_settings"))
        await session.commit()

    read = await client.get(url(store), headers=ALICE)
    saved = await client.patch(url(store), json={"tax_rate_bps": 300}, headers=ALICE)

    assert read.status_code == 200 and values(read) == DEFAULTS
    assert saved.status_code == 200 and values(saved)["tax_rate_bps"] == 300
