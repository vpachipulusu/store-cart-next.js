"""Store migration 0010 (the ``orders.oversold`` flag, KAN-72) against a real Postgres.

Orders written before 0010 survive the upgrade with the flag false, the flag defaults to
false for code that never writes it, and the downgrade back to 0009 works. Reuses the
fixtures of the store migration suite; skipped when ``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator, Callable

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
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
async def at_0009(
    world: World,  # noqa: F811
) -> AsyncIterator[tuple[World, str, AsyncEngine]]:
    database = await world.store_database("ovs10")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_to("0009", down=True))
        yield world, database, engine
    finally:
        await engine.dispose()


_INSERT_ORDER = text(
    "INSERT INTO orders (id, status, currency, subtotal_minor, tax_minor, total_minor)"
    " VALUES (:id, :status, 'GBP', 100, 0, 100)"
)


async def test_orders_from_before_0010_survive_upgrade_and_downgrade(
    at_0009: tuple[World, str, AsyncEngine],
) -> None:
    built, database, engine = at_0009
    ids = {status: new_id() for status in ("pending", "paid", "cancelled")}
    async with engine.begin() as connection:
        for status, order_id in ids.items():
            await connection.execute(_INSERT_ORDER, {"id": order_id, "status": status})

    async with engine.begin() as connection:
        await connection.run_sync(_to("0010", down=False))
    async with engine.connect() as connection:
        flags = (
            await connection.scalars(text("SELECT oversold FROM orders ORDER BY id"))
        ).all()
    async with engine.begin() as connection:
        await connection.run_sync(_to("0009", down=True))
    async with engine.connect() as connection:
        left_over = await connection.scalar(
            text(
                "SELECT (SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'orders' AND column_name = 'oversold')"
                " + (SELECT count(*) FROM pg_indexes"
                " WHERE indexname = 'ix_orders_oversold')"
            )
        )
        survivors = await connection.scalar(text("SELECT count(*) FROM orders"))
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))  # and up again

    assert flags == [False, False, False]
    assert (left_over, survivors) == (0, 3)
    assert await built.stamped_revision(database) == "0010"


async def test_the_flag_defaults_to_false_and_is_never_null(
    at_0009: tuple[World, str, AsyncEngine],
) -> None:
    _world, _database, engine = at_0009
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    order_id = new_id()

    async with engine.begin() as connection:
        await connection.execute(_INSERT_ORDER, {"id": order_id, "status": "pending"})
    async with engine.connect() as connection:
        value = await connection.scalar(
            text("SELECT oversold FROM orders WHERE id = :id"), {"id": order_id}
        )
        nullable = await connection.scalar(
            text(
                "SELECT is_nullable FROM information_schema.columns"
                " WHERE table_name = 'orders' AND column_name = 'oversold'"
            )
        )

    assert (value, nullable) == (False, "NO")
