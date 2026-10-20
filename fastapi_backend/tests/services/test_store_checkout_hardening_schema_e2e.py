"""Store migration 0009 (one open checkout order per cart, KAN-256) against a real Postgres.

Orders written before 0009 survive the upgrade (pending ones get an expiry that outlives any
session they may hold), at most one pending order can point at a cart while cancelled ones
pile up freely, and the downgrade back to 0008 works. Reuses the fixtures of the store
migration suite; skipped when ``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator, Callable
from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.ids import new_id
from app.services.store_migrations import (
    STORE_SCRIPT_LOCATION,
    _alembic_config,
    migrate_store,
)
from tests.pg_scaffold import TEST_DATABASE_URL, url_for
from tests.services.test_store_migrations_e2e import (  # noqa: F401  (fixtures)
    World,
    baseline,
    server,
    world,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


def _to(revision: str, *, down: bool) -> Callable[[Connection], None]:
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def run(connection: Connection) -> None:
        config.attributes["connection"] = connection
        (command.downgrade if down else command.upgrade)(config, revision)

    return run


@pytest.fixture
async def at_0008(
    world: World,  # noqa: F811
) -> AsyncIterator[tuple[World, str, AsyncEngine]]:
    database = await world.store_database("chk9")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_to("0008", down=True))
        yield world, database, engine
    finally:
        await engine.dispose()


_INSERT_LEGACY = text(
    "INSERT INTO orders (id, status, currency, subtotal_minor, tax_minor, total_minor,"
    " stripe_checkout_session_id, created_at)"
    " VALUES (:id, :status, 'GBP', 100, 0, 100, :session, now() - interval '2 days')"
)
_INSERT_CART = text(
    "INSERT INTO carts (id, token_hash, expires_at)"
    " VALUES (:id, :hash, now() + interval '1 day')"
)
_INSERT_ORDER = text(
    "INSERT INTO orders (id, status, currency, subtotal_minor, tax_minor, total_minor,"
    " cart_id) VALUES (:id, :status, 'GBP', 100, 0, 100, :cart)"
)


async def test_orders_from_before_0009_survive_upgrade_and_downgrade(
    at_0008: tuple[World, str, AsyncEngine],
) -> None:
    built, database, engine = at_0008
    pending, paid, cancelled = new_id(), new_id(), new_id()
    async with engine.begin() as connection:
        for order_id, status, session in (
            (pending, "pending", "cs_test_old"),
            (paid, "paid", "cs_test_paid"),
            (cancelled, "cancelled", None),
        ):
            await connection.execute(
                _INSERT_LEGACY,
                {"id": order_id, "status": status, "session": session},
            )

    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    async with engine.connect() as connection:
        rows = {
            row.id: row
            for row in await connection.execute(
                text(
                    "SELECT id, cart_id, checkout_expires_at, checkout_fingerprint,"
                    " stripe_checkout_url, created_at FROM orders"
                )
            )
        }
    async with engine.begin() as connection:
        await connection.run_sync(_to("0008", down=True))
    async with engine.connect() as connection:
        left_over = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_indexes WHERE tablename = 'orders'"
                " AND indexname IN ('uq_orders_open_checkout_per_cart',"
                " 'ix_orders_cart_id', 'ix_orders_pending_checkout_expires_at')"
            )
        )
        columns = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'orders' AND column_name IN ('cart_id',"
                " 'checkout_fingerprint', 'stripe_checkout_url', 'checkout_expires_at')"
            )
        )
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))  # and up again

    assert (left_over, columns) == (0, 0)
    assert set(rows) == {pending, paid, cancelled}
    assert rows[pending].cart_id is None
    assert rows[pending].checkout_fingerprint is None
    assert rows[pending].stripe_checkout_url is None
    # A legacy session had Stripe's default 24 hour life: the expiry never undercuts it.
    assert rows[pending].checkout_expires_at is not None
    assert rows[pending].checkout_expires_at >= rows[pending].created_at + timedelta(
        hours=24
    )
    assert rows[paid].checkout_expires_at is None
    assert rows[cancelled].checkout_expires_at is None
    async with engine.begin() as connection:
        await connection.run_sync(_to("0008", down=True))
    assert await built.stamped_revision(database) == "0008"


async def test_a_cart_has_at_most_one_pending_order(
    at_0008: tuple[World, str, AsyncEngine],
) -> None:
    _world, _database, engine = at_0008
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    cart_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(_INSERT_CART, {"id": cart_id, "hash": "a" * 64})
        await connection.execute(
            _INSERT_ORDER, {"id": new_id(), "status": "pending", "cart": cart_id}
        )

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                _INSERT_ORDER, {"id": new_id(), "status": "pending", "cart": cart_id}
            )


async def test_cancelled_and_paid_orders_do_not_block_a_new_pending_order(
    at_0008: tuple[World, str, AsyncEngine],
) -> None:
    _world, _database, engine = at_0008
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    cart_id = new_id()

    async with engine.begin() as connection:
        await connection.execute(_INSERT_CART, {"id": cart_id, "hash": "b" * 64})
        for status in ("cancelled", "cancelled", "paid", "pending"):
            await connection.execute(
                _INSERT_ORDER, {"id": new_id(), "status": status, "cart": cart_id}
            )

    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM orders WHERE cart_id = :cart"), {"cart": cart_id}
        )
    assert count == 4


async def test_orders_without_a_cart_are_not_limited(
    at_0008: tuple[World, str, AsyncEngine],
) -> None:
    _world, _database, engine = at_0008
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))

    async with engine.begin() as connection:
        for _ in range(2):
            await connection.execute(
                _INSERT_ORDER, {"id": new_id(), "status": "pending", "cart": None}
            )


async def test_deleting_a_cart_keeps_its_orders(
    at_0008: tuple[World, str, AsyncEngine],
) -> None:
    _world, _database, engine = at_0008
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    cart_id, order_id = new_id(), new_id()
    async with engine.begin() as connection:
        await connection.execute(_INSERT_CART, {"id": cart_id, "hash": "c" * 64})
        await connection.execute(
            _INSERT_ORDER, {"id": order_id, "status": "pending", "cart": cart_id}
        )

    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM carts WHERE id = :id"), {"id": cart_id}
        )

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT cart_id FROM orders WHERE id = :id"), {"id": order_id}
            )
        ).one()
    assert row.cart_id is None
