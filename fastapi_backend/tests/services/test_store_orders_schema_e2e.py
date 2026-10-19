"""Order tables of the store schema against a real Postgres (KAN-78).

Migrates a throwaway store database through ``migrate_store`` and exercises the constraints
with plain SQL. Reuses the fixtures of the catalogue schema suite; skipped when
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
from tests.services.test_store_catalogue_schema_e2e import (
    assert_rejected,
    insert,
    product,
    variant,
    violates,
)
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

NEW_TABLES = {"orders", "order_items"}


@pytest.fixture
async def conn(world: World) -> AsyncIterator[AsyncConnection]:  # noqa: F811
    database = await world.store_database("ord2")
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


async def item(conn: AsyncConnection, order_id: str, **extra: object) -> str:
    return await insert(
        conn,
        "order_items",
        {
            "id": new_id(),
            "order_id": order_id,
            "product_name": "Tee",
            "sku": "TEE-1",
            "unit_price_minor": 1000,
            "quantity": 2,
            "tax_rate_bps": 2000,
            "tax_minor": 400,
            **extra,
        },
    )


async def test_migration_creates_the_order_tables(conn: AsyncConnection):
    rows = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    )

    assert NEW_TABLES <= {row[0] for row in rows}


async def test_order_defaults_to_pending(conn: AsyncConnection):
    oid = await order(conn)

    status = await scalar(conn, "SELECT status FROM orders WHERE id = :i", i=oid)

    assert status == "pending"


@pytest.mark.parametrize(
    "status", ["pending", "paid", "fulfilled", "cancelled", "refunded"]
)
async def test_every_status_of_the_flow_is_accepted(conn: AsyncConnection, status: str):
    tracking = "TRK-1" if status == "fulfilled" else None
    oid = await order(conn, status=status, tracking_number=tracking)

    stored = await scalar(conn, "SELECT status FROM orders WHERE id = :i", i=oid)

    assert stored == status


@pytest.mark.parametrize("status", ["shipped", "PAID", "", "void"])
async def test_unknown_status_is_rejected(conn: AsyncConnection, status: str):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO orders (id, currency, subtotal_minor, tax_minor, total_minor,"
            " status) VALUES ('o', 'GBP', 0, 0, 0, :s)"
        ).bindparams(s=status),
        "ck_orders_status",
    )


@pytest.mark.parametrize("currency", ["gbp", "GB", "GBPP", "G1P", "", "£££"])
async def test_currency_must_be_three_upper_case_letters(
    conn: AsyncConnection, currency: str
):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO orders (id, currency, subtotal_minor, tax_minor, total_minor)"
            " VALUES ('o', :c, 0, 0, 0)"
        ).bindparams(c=currency),
        "ck_orders_currency",
    )


@pytest.mark.parametrize(
    ("subtotal", "tax", "total", "constraint"),
    [
        (-1, 0, -1, "ck_orders_subtotal_minor"),
        (0, -1, -1, "ck_orders_tax_minor"),
        (100, 20, 121, "ck_orders_total_minor"),
        (100, 20, 119, "ck_orders_total_minor"),
    ],
)
async def test_order_money_is_non_negative_and_adds_up(
    conn: AsyncConnection, subtotal: int, tax: int, total: int, constraint: str
):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO orders (id, currency, subtotal_minor, tax_minor, total_minor)"
            " VALUES ('o', 'GBP', :s, :t, :g)"
        ).bindparams(s=subtotal, t=tax, g=total),
        constraint,
    )


async def test_order_item_belongs_to_an_existing_order(conn: AsyncConnection):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO order_items (id, order_id, product_name, sku, unit_price_minor,"
            " quantity, tax_rate_bps, tax_minor)"
            " VALUES ('i', 'missing', 'T', 'S', 1, 1, 0, 0)"
        ),
        "fk_order_items_order",
    )


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("quantity", 0, "ck_order_items_quantity"),
        ("quantity", -1, "ck_order_items_quantity"),
        ("quantity", 10_001, "ck_order_items_quantity"),
        ("unit_price_minor", -1, "ck_order_items_unit_price_minor"),
        ("tax_minor", -1, "ck_order_items_tax_minor"),
        ("tax_rate_bps", -1, "ck_order_items_tax_rate_bps"),
        ("tax_rate_bps", 100_001, "ck_order_items_tax_rate_bps"),
        ("product_name", " ", "ck_order_items_product_name"),
        ("product_name", "x" * 256, "ck_order_items_product_name"),
        ("sku", "", "ck_order_items_sku"),
        ("variant_label", "x" * 256, "ck_order_items_variant_label"),
    ],
)
async def test_bad_order_item_values_are_rejected(
    conn: AsyncConnection, column: str, value: object, constraint: str
):
    oid = await order(conn)

    await _reject_item(conn, oid, column, value, constraint)


async def _reject_item(
    conn: AsyncConnection, oid: str, column: str, value: object, constraint: str
) -> None:
    values: dict[str, object] = {
        "id": "i",
        "order_id": oid,
        "product_name": "T",
        "sku": "S",
        "unit_price_minor": 1,
        "quantity": 1,
        "tax_rate_bps": 0,
        "tax_minor": 0,
        column: value,
    }
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    await assert_rejected(
        conn,
        text(f"INSERT INTO order_items ({columns}) VALUES ({params})").bindparams(
            **values
        ),
        constraint,
    )


async def test_item_snapshot_survives_a_product_and_variant_price_change(
    conn: AsyncConnection,
):
    pid = await product(conn)
    vid = await variant(conn, pid, sku="TEE-1")
    oid = await order(conn)
    iid = await item(
        conn,
        oid,
        product_id=pid,
        variant_id=vid,
        product_name="Tee",
        variant_label="Large",
        unit_price_minor=1999,
    )

    await conn.execute(
        text("UPDATE products SET title = 'Renamed', updated_at = now() WHERE id = :p"),
        {"p": pid},
    )
    await conn.execute(
        text("UPDATE variants SET price_minor = 5000, sku = 'NEW-1' WHERE id = :v"),
        {"v": vid},
    )

    row = (
        await conn.execute(
            text(
                "SELECT product_name, sku, variant_label, unit_price_minor "
                "FROM order_items WHERE id = :i"
            ),
            {"i": iid},
        )
    ).one()
    assert tuple(row) == ("Tee", "TEE-1", "Large", 1999)


async def test_deleting_a_product_keeps_the_item_and_nulls_the_references(
    conn: AsyncConnection,
):
    pid = await product(conn)
    vid = await variant(conn, pid)
    oid = await order(conn)
    iid = await item(conn, oid, product_id=pid, variant_id=vid)

    await conn.execute(text("DELETE FROM products WHERE id = :p"), {"p": pid})

    row = (
        await conn.execute(
            text(
                "SELECT product_id, variant_id, product_name FROM order_items "
                "WHERE id = :i"
            ),
            {"i": iid},
        )
    ).one()
    assert tuple(row) == (None, None, "Tee")


async def test_deleting_a_variant_alone_keeps_the_item(conn: AsyncConnection):
    pid = await product(conn)
    vid = await variant(conn, pid)
    oid = await order(conn)
    iid = await item(conn, oid, product_id=pid, variant_id=vid)

    await conn.execute(text("DELETE FROM variants WHERE id = :v"), {"v": vid})

    row = (
        await conn.execute(
            text("SELECT product_id, variant_id FROM order_items WHERE id = :i"),
            {"i": iid},
        )
    ).one()
    assert tuple(row) == (pid, None)


async def test_deleting_an_order_removes_its_items(conn: AsyncConnection):
    oid = await order(conn)
    await item(conn, oid)

    await conn.execute(text("DELETE FROM orders WHERE id = :o"), {"o": oid})

    assert await scalar(conn, "SELECT count(*) FROM order_items") == 0


async def test_downgrade_drops_the_order_tables_and_keeps_the_catalogue(
    conn: AsyncConnection,
):
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def run(connection: Connection, action: str, target: str) -> None:
        config.attributes["connection"] = connection
        getattr(command, action)(config, target)

    await conn.run_sync(run, "downgrade", "0003")
    gone = [
        await scalar(conn, f"SELECT to_regclass('{name}')")
        for name in sorted(NEW_TABLES)
    ]
    kept = await scalar(conn, "SELECT to_regclass('product_images')")
    stamped = await scalar(conn, "SELECT version_num FROM store_alembic_version")
    await conn.run_sync(run, "upgrade", "head")
    back = await scalar(conn, "SELECT to_regclass('order_items')")

    assert gone == [None, None]
    assert kept is not None
    assert stamped == "0003"
    assert back is not None


async def test_a_store_at_0003_with_data_reaches_head_through_the_migrate_path(
    world: World,  # noqa: F811
):
    database = await world.store_database("old3")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def downgrade(connection: Connection) -> None:
        config.attributes["connection"] = connection
        command.downgrade(config, "0003")

    try:
        async with engine.begin() as connection:
            await connection.run_sync(downgrade)
            await connection.execute(
                text("INSERT INTO products (id, title, slug) VALUES ('p', 'T', 'tee')")
            )
        assert await world.stamped_revision(database) == "0003"

        await migrate_store(store_id, world.provider)

        async with engine.connect() as connection:
            products = await scalar(connection, "SELECT count(*) FROM products")
            orders = await scalar(connection, "SELECT to_regclass('orders')")
        assert await world.stamped_revision(database) == "0007"  # head
        assert products == 1
        assert orders is not None
    finally:
        await engine.dispose()


async def test_a_variant_appears_on_one_line_per_order(conn: AsyncConnection):
    pid = await product(conn)
    vid = await variant(conn, pid)
    oid = await order(conn)
    await item(conn, oid, product_id=pid, variant_id=vid)

    async with violates(conn, "uq_order_items_order_variant"):
        await item(conn, oid, product_id=pid, variant_id=vid)


async def test_lines_whose_variant_was_deleted_may_repeat(conn: AsyncConnection):
    oid = await order(conn)
    await item(conn, oid, variant_id=None)
    await item(conn, oid, variant_id=None)

    assert await scalar(conn, "SELECT count(*) FROM order_items") == 2
