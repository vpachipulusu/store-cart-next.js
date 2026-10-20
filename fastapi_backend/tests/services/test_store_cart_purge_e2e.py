"""The scheduled expired-cart purge on real store databases (KAN-252).

Bounded per store (a batch) and per run (a number of stores), skips live carts, and one store
that cannot be opened does not stop the others. Runs only when ``TEST_DATABASE_URL`` points at a
throwaway local server.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.ids import new_id
from app.services import store_cart_purge
from app.services.store_cart_purge import purge_expired_carts
from app.services.store_sessions import open_store_session
from tests.api.products_support import store_of, world  # noqa: F401  (fixture)
from tests.isolation_world import World
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

STORES = (("a", "north"), ("b", "north"))
EXPIRED = timedelta(days=-1)
LIVE = timedelta(days=30)


async def insert_carts(world: World, store_id: str, *, expired: int, live: int) -> None:
    async with open_store_session(store_id, world.provider) as session:
        for delta, count in ((EXPIRED, expired), (LIVE, live)):
            for _ in range(count):
                cart_id = new_id()
                await session.execute(
                    text(
                        "INSERT INTO carts (id, token_hash, expires_at) "
                        "VALUES (:id, :hash, now() + :delta)"
                    ),
                    {
                        "id": cart_id,
                        "hash": hashlib.sha256(cart_id.encode()).hexdigest(),
                        "delta": delta,
                    },
                )
        await session.commit()


async def counts(world: World, store_id: str) -> tuple[int, int]:
    """(expired, live) cart rows in one store."""
    expired = await world.store_value(
        store_id, "SELECT count(*) FROM carts WHERE expires_at <= now()"
    )
    live = await world.store_value(
        store_id, "SELECT count(*) FROM carts WHERE expires_at > now()"
    )
    return int(expired), int(live)


async def clear(world: World) -> None:
    for label, slug in STORES:
        async with open_store_session(
            store_of(world, label, slug), world.provider
        ) as session:
            await session.execute(text("DELETE FROM carts"))
            await session.commit()


@asynccontextmanager
async def unopenable(world: World, store_id: str) -> AsyncIterator[None]:
    """Make one store's connection string undecryptable, then restore it."""
    select = text("SELECT connection_string_encrypted FROM stores WHERE id = :id")
    async with world.platform.begin() as connection:
        saved = (await connection.execute(select, {"id": store_id})).scalar_one()
        await connection.execute(
            text(
                "UPDATE stores SET connection_string_encrypted = 'not-an-envelope' "
                "WHERE id = :id"
            ),
            {"id": store_id},
        )
    try:
        yield
    finally:
        async with world.platform.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE stores SET connection_string_encrypted = :v WHERE id = :id"
                ),
                {"v": saved, "id": store_id},
            )


async def test_expired_carts_are_removed_and_live_ones_stay(world: World) -> None:
    await clear(world)
    store_id = store_of(world, "a", "north")
    await insert_carts(world, store_id, expired=5, live=3)

    summary = await purge_expired_carts(world.provider, max_stores=100, batch=100)

    assert await counts(world, store_id) == (0, 3)
    assert summary.carts_deleted >= 5
    assert summary.stores_failed == 0


async def test_a_run_removes_at_most_one_batch_per_store(world: World) -> None:
    await clear(world)
    first, second = (store_of(world, label, slug) for label, slug in STORES)
    await insert_carts(world, first, expired=7, live=1)
    await insert_carts(world, second, expired=4, live=0)

    run_one = await purge_expired_carts(world.provider, max_stores=100, batch=3)

    assert await counts(world, first) == (4, 1)
    assert await counts(world, second) == (1, 0)
    assert run_one.carts_deleted >= 6

    await purge_expired_carts(world.provider, max_stores=100, batch=3)
    await purge_expired_carts(world.provider, max_stores=100, batch=3)
    assert await counts(world, first) == (0, 1)
    assert await counts(world, second) == (0, 0)


async def test_a_run_visits_at_most_max_stores(world: World) -> None:
    summary = await purge_expired_carts(world.provider, max_stores=1, batch=10)

    assert summary.stores == 1


async def test_a_spent_time_budget_ends_the_run_before_the_next_store(
    world: World,
) -> None:
    await clear(world)
    store_id = store_of(world, "a", "north")
    await insert_carts(world, store_id, expired=3, live=0)
    ticks = iter([0.0, 0.0, 99.0, 99.0, 99.0, 99.0])

    summary = await purge_expired_carts(
        world.provider,
        max_stores=100,
        batch=10,
        time_budget_seconds=5.0,
        clock=lambda: next(ticks),
    )

    assert summary.stores == 1


async def test_a_store_that_cannot_be_opened_does_not_stop_the_others(
    world: World,
) -> None:
    await clear(world)
    broken, healthy = (store_of(world, label, slug) for label, slug in STORES)
    await insert_carts(world, healthy, expired=2, live=0)

    async with unopenable(world, broken):
        summary = await purge_expired_carts(world.provider, max_stores=100, batch=10)

    assert summary.stores_failed == 1
    assert await counts(world, healthy) == (0, 0)  # the others were still purged


async def test_the_defaults_are_bounded() -> None:
    assert 0 < store_cart_purge.EXPIRED_CARTS_PER_STORE <= 5000
    assert 0 < store_cart_purge.STORES_PER_RUN <= 200
    assert (
        0
        < store_cart_purge.PER_STORE_SECONDS
        < store_cart_purge.RUN_TIME_BUDGET_SECONDS
    )


async def test_a_hanging_store_is_cut_off_per_store_and_the_others_still_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang(store_id: str, provider: object, batch: int) -> int:
        await asyncio.sleep(60)
        return 0

    monkeypatch.setattr(store_cart_purge, "_purge_store", hang)

    summary = await asyncio.wait_for(
        purge_expired_carts(
            world.provider,
            max_stores=100,
            batch=10,
            time_budget_seconds=60.0,
            per_store_seconds=0.05,
        ),
        timeout=30,
    )

    assert summary.stores >= 2
    assert summary.stores_failed == summary.stores


async def test_a_cart_being_written_is_skipped_not_waited_for(world: World) -> None:
    await clear(world)
    store_id = store_of(world, "a", "north")
    await insert_carts(world, store_id, expired=3, live=0)
    async with open_store_session(store_id, world.provider) as writer:
        await writer.execute(
            text(
                "SELECT id FROM carts WHERE expires_at <= now() "
                "ORDER BY id LIMIT 1 FOR UPDATE"
            )
        )

        summary = await asyncio.wait_for(
            purge_expired_carts(world.provider, max_stores=100, batch=10),
            timeout=30,
        )
        remaining = await counts(world, store_id)
        await writer.rollback()

    assert summary.stores_failed == 0
    assert remaining == (1, 0)
