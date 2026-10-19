"""Fulfilment columns of the orders table against a real Postgres (KAN-79, store revision 0005).

Constraints are exercised with plain SQL on a throwaway store database; the service-level
behaviour (``fulfil_order``) is in ``test_store_orders_e2e.py``. Skipped when
``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.ids import new_id
from app.services.store_migrations import (
    STORE_SCRIPT_LOCATION,
    _alembic_config,
    migrate_store,
)
from tests.pg_scaffold import TEST_DATABASE_URL, url_for
from tests.services.test_store_catalogue_schema_e2e import insert, violates
from tests.services.test_store_categories_images_schema_e2e import scalar
from tests.services.test_store_migrations_e2e import (  # noqa: F401  (fixtures)
    World,
    server,
    world,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture
async def conn(world: World) -> AsyncIterator[AsyncConnection]:  # noqa: F811
    database = await world.store_database("ful5")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def order(conn: AsyncConnection, **extra: object) -> str:
    return await insert(
        conn,
        "orders",
        {
            "id": new_id(),
            "currency": "GBP",
            "subtotal_minor": 2000,
            "tax_minor": 400,
            "total_minor": 2400,
            **extra,
        },
    )


async def test_new_orders_have_no_fulfilment_data(conn: AsyncConnection):
    oid = await order(conn)

    row = (
        await conn.execute(
            text(
                "SELECT tracking_number, carrier, fulfilled_at FROM orders WHERE id = :i"
            ),
            {"i": oid},
        )
    ).one()

    assert tuple(row) == (None, None, None)


async def test_a_fulfilled_order_needs_a_tracking_number(conn: AsyncConnection):
    async with violates(conn, "ck_orders_fulfilled_tracking"):
        await order(conn, status="fulfilled")


async def test_a_fulfilled_order_with_a_tracking_number_is_accepted(
    conn: AsyncConnection,
):
    oid = await order(conn, status="fulfilled", tracking_number="TRK-1")

    assert (
        await scalar(conn, "SELECT status FROM orders WHERE id = :i", i=oid)
        == "fulfilled"
    )


async def test_a_paid_order_may_have_no_tracking_number(conn: AsyncConnection):
    oid = await order(conn, status="paid")

    assert (
        await scalar(conn, "SELECT tracking_number FROM orders WHERE id = :i", i=oid)
        is None
    )


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("tracking_number", "", "ck_orders_tracking_number"),
        ("tracking_number", "x" * 101, "ck_orders_tracking_number"),
        ("carrier", "", "ck_orders_carrier"),
        ("carrier", "y" * 101, "ck_orders_carrier"),
    ],
)
async def test_tracking_text_length_is_limited(
    conn: AsyncConnection, column: str, value: str, constraint: str
):
    async with violates(conn, constraint):
        await order(conn, **{column: value})


@pytest.mark.parametrize("column", ["tracking_number", "carrier"])
async def test_tracking_text_at_the_limit_is_accepted(
    conn: AsyncConnection, column: str
):
    oid = await order(conn, **{column: "z" * 100})

    assert await scalar(conn, f"SELECT {column} FROM orders WHERE id = :i", i=oid)


async def test_downgrade_removes_the_columns_and_keeps_the_orders(
    conn: AsyncConnection,
):
    oid = await order(conn)
    await conn.commit()
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def run(connection: Connection, action: str, target: str) -> None:
        config.attributes["connection"] = connection
        getattr(command, action)(config, target)

    await conn.run_sync(run, "downgrade", "0004")
    columns = {
        row[0]
        for row in await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'orders'"
            )
        )
    }
    kept = await scalar(conn, "SELECT count(*) FROM orders WHERE id = :i", i=oid)
    stamped = await scalar(conn, "SELECT version_num FROM store_alembic_version")
    await conn.run_sync(run, "upgrade", "head")
    back = await scalar(
        conn,
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'orders' AND column_name = 'tracking_number'",
    )

    assert not columns & {"tracking_number", "carrier", "fulfilled_at"}
    assert kept == 1
    assert stamped == "0004"
    assert back == 1
