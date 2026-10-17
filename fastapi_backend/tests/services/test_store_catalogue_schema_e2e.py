"""Catalogue tables of the store schema against a real Postgres (KAN-70).

Migrates a throwaway store database through ``migrate_store`` (so the real store tree runs)
and then exercises the constraints with plain SQL. Reuses the world fixtures of the store
migration suite; skipped when ``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.sql.base import Executable

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

CATALOGUE_TABLES = {
    "products",
    "product_options",
    "product_option_values",
    "variants",
    "variant_option_values",
}
LINK = text(
    "INSERT INTO variant_option_values "
    "(variant_id, option_id, option_value_id, product_id) VALUES (:i, :o, :v, :p)"
)


@pytest.fixture
async def conn(world: World) -> AsyncIterator[AsyncConnection]:  # noqa: F811
    database = await world.store_database("cat")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def insert(conn: AsyncConnection, table: str, values: dict[str, object]) -> str:
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    await conn.execute(
        text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values
    )
    return str(values["id"])


async def product(conn: AsyncConnection, slug: str = "tee", **extra: object) -> str:
    return await insert(
        conn, "products", {"id": new_id(), "title": "Tee", "slug": slug, **extra}
    )


async def variant(
    conn: AsyncConnection, product_id: str, sku: str = "TEE-1", **extra: object
) -> str:
    return await insert(
        conn,
        "variants",
        {
            "id": new_id(),
            "product_id": product_id,
            "sku": sku,
            "price_minor": 1999,
            **extra,
        },
    )


async def option(
    conn: AsyncConnection, product_id: str, name: str, *values: str
) -> tuple[str, list[str]]:
    option_id = await insert(
        conn,
        "product_options",
        {"id": new_id(), "product_id": product_id, "name": name},
    )
    value_ids = [
        await insert(
            conn,
            "product_option_values",
            {"id": new_id(), "option_id": option_id, "value": value},
        )
        for value in values
    ]
    return option_id, value_ids


def violated_constraint(error: IntegrityError) -> str | None:
    """The constraint or index name asyncpg reports for the violation."""
    driver_error = error.orig.__cause__ if error.orig is not None else None
    return getattr(driver_error, "constraint_name", None)


@asynccontextmanager
async def violates(conn: AsyncConnection, *constraints: str) -> AsyncIterator[None]:
    """The block must fail on one of ``constraints``; the transaction is rolled back."""
    await conn.commit()
    with pytest.raises(IntegrityError) as caught:
        yield
        await conn.commit()  # deferred constraints are checked here
    await conn.rollback()
    assert violated_constraint(caught.value) in constraints


async def assert_rejected(
    conn: AsyncConnection, statement: Executable, constraint: str
) -> None:
    async with violates(conn, constraint):
        await conn.execute(statement)


async def test_migration_creates_the_catalogue_tables(conn: AsyncConnection):
    rows = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    )

    assert CATALOGUE_TABLES <= {row[0] for row in rows}


async def test_product_defaults_to_draft_and_accepts_active(conn: AsyncConnection):
    draft = await product(conn, "a")
    active = await product(conn, "b", status="active")

    result = await conn.execute(
        text("SELECT id, status FROM products WHERE id IN (:a, :b)"),
        {"a": draft, "b": active},
    )
    rows = {row[0]: row[1] for row in result}
    assert rows == {draft: "draft", active: "active"}


async def test_unknown_product_status_is_rejected(conn: AsyncConnection):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO products (id, title, slug, status) "
            "VALUES ('x', 'T', 's', 'archived')"
        ),
        "ck_products_status",
    )


async def test_product_slug_is_unique_per_store(conn: AsyncConnection):
    await product(conn, "tee")

    await assert_rejected(
        conn,
        text("INSERT INTO products (id, title, slug) VALUES ('y', 'T', 'tee')"),
        "uq_products_slug",
    )


@pytest.mark.parametrize(
    "slug", ["Tee", "a b", "-a", "a-", "a--b", "", "a_b", "abc\n", "x" * 201]
)
async def test_bad_slug_is_rejected(conn: AsyncConnection, slug: str):
    await assert_rejected(
        conn,
        text("INSERT INTO products (id, title, slug) VALUES ('z', 'T', :s)").bindparams(
            s=slug
        ),
        "ck_products_slug_format",
    )


@pytest.mark.parametrize("title", ["", "  ", "\t\n", "x" * 256])
async def test_blank_or_oversized_title_is_rejected(conn: AsyncConnection, title: str):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO products (id, title, slug) VALUES ('t', :t, 'ok')"
        ).bindparams(t=title),
        "ck_products_title",
    )


async def test_variant_holds_price_compare_at_weight_and_stock(conn: AsyncConnection):
    vid = await variant(
        conn,
        await product(conn),
        compare_at_price_minor=2999,
        weight_grams=250,
        stock=7,
    )

    row = (
        await conn.execute(
            text(
                "SELECT sku, price_minor, compare_at_price_minor, weight_grams, stock "
                "FROM variants WHERE id = :i"
            ),
            {"i": vid},
        )
    ).one()
    assert tuple(row) == ("TEE-1", 1999, 2999, 250, 7)


async def test_variant_stock_defaults_to_zero_and_optionals_to_null(
    conn: AsyncConnection,
):
    vid = await variant(conn, await product(conn))

    row = (
        await conn.execute(
            text(
                "SELECT stock, compare_at_price_minor, weight_grams FROM variants "
                "WHERE id = :i"
            ),
            {"i": vid},
        )
    ).one()
    assert tuple(row) == (0, None, None)


@pytest.mark.parametrize(
    ("extra", "constraint"),
    [
        ({"price_minor": -1}, "ck_variants_price_minor"),
        ({"stock": -1}, "ck_variants_stock"),
        ({"weight_grams": -1}, "ck_variants_weight_grams"),
        ({"compare_at_price_minor": 1999}, "ck_variants_compare_at_above_price"),
        ({"compare_at_price_minor": 100}, "ck_variants_compare_at_above_price"),
        ({"sku": ""}, "ck_variants_sku_format"),
        ({"sku": " A "}, "ck_variants_sku_format"),
        ({"sku": "A\t"}, "ck_variants_sku_format"),
        ({"sku": "A\nB"}, "ck_variants_sku_format"),
        ({"sku": "A\n"}, "ck_variants_sku_format"),
        ({"sku": "A" * 101}, "ck_variants_sku_format"),
    ],
)
async def test_variant_value_constraints(
    conn: AsyncConnection, extra: dict[str, object], constraint: str
):
    pid = await product(conn)

    async with violates(conn, constraint):
        await variant(conn, pid, **extra)


async def test_sku_is_unique_case_insensitively_across_the_store(
    conn: AsyncConnection,
):
    await variant(conn, await product(conn, "a"), "Tee-1")
    other = await product(conn, "b")

    async with violates(conn, "uq_variants_sku_lower"):
        await variant(conn, other, "tee-1")


async def test_variant_requires_an_existing_product(conn: AsyncConnection):
    async with violates(conn, "fk_variants_product"):
        await variant(conn, "missing")


async def test_deleting_an_option_value_or_option_still_used_is_rejected(
    conn: AsyncConnection,
):
    pid = await product(conn)
    size, (small,) = await option(conn, pid, "Size", "S")
    await conn.execute(
        LINK, {"i": await variant(conn, pid), "o": size, "v": small, "p": pid}
    )

    async with violates(conn, "fk_variant_option_values_value_option"):
        await conn.execute(
            text("DELETE FROM product_option_values WHERE id = :v"), {"v": small}
        )
    # Deleting the option also deletes its values; either link key may report first.
    async with violates(
        conn,
        "fk_variant_option_values_value_option",
        "fk_variant_option_values_option_product",
    ):
        await conn.execute(
            text("DELETE FROM product_options WHERE id = :o"), {"o": size}
        )

    links = (
        await conn.execute(text("SELECT count(*) FROM variant_option_values"))
    ).scalar_one()
    assert links == 1


async def test_an_unused_option_value_can_be_deleted(conn: AsyncConnection):
    pid = await product(conn)
    _, (small, large) = await option(conn, pid, "Size", "S", "L")

    await conn.execute(
        text("DELETE FROM product_option_values WHERE id = :v"), {"v": large}
    )

    remaining = (
        (
            await conn.execute(
                text("SELECT id FROM product_option_values WHERE id IN (:a, :b)"),
                {"a": small, "b": large},
            )
        )
        .scalars()
        .all()
    )
    assert remaining == [small]


async def test_deleting_a_product_removes_its_variants_options_and_values(
    conn: AsyncConnection,
):
    pid = await product(conn)
    size, (small,) = await option(conn, pid, "Size", "S")
    await conn.execute(
        LINK, {"i": await variant(conn, pid), "o": size, "v": small, "p": pid}
    )

    await conn.execute(text("DELETE FROM products WHERE id = :p"), {"p": pid})

    for table in (
        "variants",
        "product_options",
        "product_option_values",
        "variant_option_values",
    ):
        count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
        assert count == 0, table


async def test_option_names_and_values_are_unique_within_their_parent(
    conn: AsyncConnection,
):
    pid = await product(conn)
    size, _ = await option(conn, pid, "Size", "S")

    await assert_rejected(
        conn,
        text(
            "INSERT INTO product_options (id, product_id, name) VALUES ('d', :p, 'size')"
        ).bindparams(p=pid),
        "uq_product_options_product_name",
    )
    await assert_rejected(
        conn,
        text(
            "INSERT INTO product_option_values (id, option_id, value) "
            "VALUES ('d', :o, 's')"
        ).bindparams(o=size),
        "uq_product_option_values_option_value",
    )


async def test_a_variant_takes_one_value_per_option_from_that_option(
    conn: AsyncConnection,
):
    pid = await product(conn)
    size, (small, large) = await option(conn, pid, "Size", "S", "L")
    color, (red,) = await option(conn, pid, "Color", "Red")
    first, second = await variant(conn, pid), await variant(conn, pid, "TEE-2")
    await conn.execute(LINK, {"i": first, "o": size, "v": small, "p": pid})
    await conn.execute(LINK, {"i": first, "o": color, "v": red, "p": pid})

    # a second value for the same option
    await assert_rejected(
        conn,
        LINK.bindparams(i=first, o=size, v=large, p=pid),
        "variant_option_values_pkey",
    )
    # a value that belongs to a different option
    await assert_rejected(
        conn,
        LINK.bindparams(i=second, o=color, v=small, p=pid),
        "fk_variant_option_values_value_option",
    )


async def test_a_variant_cannot_use_an_option_of_another_product(
    conn: AsyncConnection,
):
    mine, other = await product(conn, "mine"), await product(conn, "other")
    size, (small,) = await option(conn, other, "Size", "S")
    own_variant = await variant(conn, mine)

    await assert_rejected(
        conn,
        LINK.bindparams(i=own_variant, o=size, v=small, p=mine),
        "fk_variant_option_values_option_product",
    )
    await assert_rejected(
        conn,
        LINK.bindparams(i=own_variant, o=size, v=small, p=other),
        "fk_variant_option_values_variant_product",
    )


async def test_lookup_indexes_exist(conn: AsyncConnection):
    names = {
        row[0]
        for row in await conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        )
    }

    assert {
        "uq_products_slug",
        "uq_product_options_product_name",
        "uq_product_option_values_option_value",
        "uq_variants_sku_lower",
        "ix_variants_product_id",
        "ix_variant_option_values_option_value_id",
        "ix_variant_option_values_option_product",
    } <= names


async def test_downgrade_removes_the_catalogue_and_upgrade_restores_it(
    conn: AsyncConnection,
):
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def run(connection: Connection, action: str) -> None:
        config.attributes["connection"] = connection
        getattr(command, action)(config, "0001" if action == "downgrade" else "head")

    await conn.run_sync(run, "downgrade")
    gone = (await conn.execute(text("SELECT to_regclass('products')"))).scalar_one()
    await conn.run_sync(run, "upgrade")
    back = (await conn.execute(text("SELECT to_regclass('variants')"))).scalar_one()

    assert gone is None
    assert back is not None


async def test_downgrade_returns_the_version_table_to_the_baseline(
    conn: AsyncConnection,
):
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def downgrade(connection: Connection) -> None:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001")

    await conn.run_sync(downgrade)

    stamped = (
        await conn.execute(text("SELECT version_num FROM store_alembic_version"))
    ).scalar_one()
    assert stamped == "0001"


async def test_a_baseline_store_with_data_is_upgraded_intact(
    world: World,  # noqa: F811
    baseline: Path,  # noqa: F811
):
    database = await world.store_database("old")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider, script_location=baseline)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE legacy (note text)"))
            await connection.execute(text("INSERT INTO legacy VALUES ('kept')"))

        await migrate_store(store_id, world.provider)

        async with engine.connect() as connection:
            notes = (await connection.execute(text("SELECT note FROM legacy"))).all()
            tables = await connection.execute(text("SELECT to_regclass('variants')"))
            assert [row[0] for row in notes] == ["kept"]
            assert tables.scalar_one() is not None
    finally:
        await engine.dispose()
