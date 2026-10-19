"""``store_settings`` table of the store schema against a real Postgres (KAN-82, KAN-83).

Migrates a throwaway store database through ``migrate_store`` and exercises the constraints
with plain SQL. Skipped when ``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.services.store_migrations import migrate_store
from tests.pg_scaffold import TEST_DATABASE_URL, url_for
from tests.services.test_store_catalogue_schema_e2e import assert_rejected
from tests.services.test_store_categories_images_schema_e2e import scalar
from tests.services.test_store_migrations_e2e import (  # noqa: F401  (fixtures)
    World,
    baseline,
    server,
    world,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture
async def conn(world: World) -> AsyncIterator[AsyncConnection]:  # noqa: F811
    database = await world.store_database("set5")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def test_migration_seeds_one_row_with_defaults(conn: AsyncConnection):
    row = (await conn.execute(text("SELECT * FROM store_settings"))).mappings().one()

    assert row["shipping_flat_rate_minor"] == 0
    assert row["free_shipping_threshold_minor"] is None
    assert row["tax_rate_bps"] == 0
    assert row["prices_include_tax"] is False


async def test_a_second_row_is_rejected(conn: AsyncConnection):
    await assert_rejected(
        conn,
        text("INSERT INTO store_settings (id) VALUES (false)"),
        "ck_store_settings_singleton",
    )


async def test_the_singleton_key_cannot_be_duplicated(conn: AsyncConnection):
    with pytest.raises(IntegrityError, match="store_settings_pkey"):
        await conn.execute(text("INSERT INTO store_settings (id) VALUES (true)"))


@pytest.mark.parametrize(
    "column,value,constraint",
    [
        ("shipping_flat_rate_minor", -1, "ck_store_settings_shipping_flat_rate_minor"),
        (
            "shipping_flat_rate_minor",
            100_000_000_001,
            "ck_store_settings_shipping_flat_rate_minor",
        ),
        (
            "free_shipping_threshold_minor",
            0,
            "ck_store_settings_free_shipping_threshold_minor",
        ),
        ("tax_rate_bps", -1, "ck_store_settings_tax_rate_bps"),
        ("tax_rate_bps", 10_001, "ck_store_settings_tax_rate_bps"),
    ],
)
async def test_out_of_range_values_are_rejected(
    conn: AsyncConnection, column: str, value: int, constraint: str
):
    await assert_rejected(
        conn, text(f"UPDATE store_settings SET {column} = {value}"), constraint
    )


async def test_boundary_values_are_accepted(conn: AsyncConnection):
    await conn.execute(
        text(
            "UPDATE store_settings SET shipping_flat_rate_minor = 100000000000,"
            " free_shipping_threshold_minor = 1, tax_rate_bps = 10000,"
            " prices_include_tax = true"
        )
    )

    assert await scalar(conn, "SELECT tax_rate_bps FROM store_settings") == 10_000
