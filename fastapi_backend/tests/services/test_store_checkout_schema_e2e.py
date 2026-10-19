"""Store migration 0008 (checkout columns, KAN-68) against a real Postgres.

An order written before 0008 survives the upgrade and passes the new total CHECK, a Checkout
Session id can belong to one order only, and the downgrade back to 0007 works. Reuses the
fixtures of the store migration suite; skipped when ``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator, Callable

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


async def _orders(engine: AsyncEngine) -> list[dict[str, object]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT id, total_minor, shipping_minor, prices_include_tax,"
                " stripe_checkout_session_id FROM orders ORDER BY id"
            )
        )
        return [dict(row._mapping) for row in rows]


@pytest.fixture
async def at_0007(
    world: World,  # noqa: F811
) -> AsyncIterator[tuple[World, str, AsyncEngine]]:
    database = await world.store_database("chk8")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_to("0007", down=True))
        yield world, database, engine
    finally:
        await engine.dispose()


async def test_an_order_from_before_0008_survives_upgrade_and_downgrade(
    at_0007: tuple[World, str, AsyncEngine],
) -> None:
    built, database, engine = at_0007
    order_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO orders (id, currency, subtotal_minor, tax_minor, total_minor)"
                " VALUES (:id, 'GBP', 2000, 400, 2400)"
            ),
            {"id": order_id},
        )
        await connection.execute(
            text(
                "INSERT INTO order_items (id, order_id, product_name, sku,"
                " unit_price_minor, quantity, tax_rate_bps, tax_minor)"
                " VALUES (:id, :order_id, 'Tee', 'SKU-1', 1000, 2, 2000, 400)"
            ),
            {"id": new_id(), "order_id": order_id},
        )

    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    upgraded = await _orders(engine)
    async with engine.begin() as connection:
        await connection.run_sync(_to("0007", down=True))

    assert upgraded == [
        {
            "id": order_id,
            "total_minor": 2400,
            "shipping_minor": 0,
            "prices_include_tax": False,
            "stripe_checkout_session_id": None,
        }
    ]
    assert await built.stamped_revision(database) == "0007"


async def test_a_checkout_session_can_belong_to_one_order_only(
    at_0007: tuple[World, str, AsyncEngine],
) -> None:
    _world, _database, engine = at_0007
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    insert = text(
        "INSERT INTO orders (id, currency, subtotal_minor, tax_minor, total_minor,"
        " stripe_checkout_session_id) VALUES (:id, 'GBP', 100, 0, 100, 'cs_test_dup')"
    )
    async with engine.begin() as connection:
        await connection.execute(insert, {"id": new_id()})

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(insert, {"id": new_id()})


async def test_the_new_total_rule_counts_shipping_and_included_tax(
    at_0007: tuple[World, str, AsyncEngine],
) -> None:
    _world, _database, engine = at_0007
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))
    insert = text(
        "INSERT INTO orders (id, currency, subtotal_minor, shipping_minor, tax_minor,"
        " total_minor, prices_include_tax)"
        " VALUES (:id, 'GBP', 1200, 499, 200, :total, :included)"
    )
    async with engine.begin() as connection:
        await connection.execute(
            insert, {"id": new_id(), "total": 1699, "included": True}
        )
        await connection.execute(
            insert, {"id": new_id(), "total": 1899, "included": False}
        )

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                insert, {"id": new_id(), "total": 1899, "included": True}
            )
