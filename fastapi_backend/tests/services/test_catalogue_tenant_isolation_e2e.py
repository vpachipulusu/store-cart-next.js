"""Tenant isolation of the catalogue tables across two real store databases (KAN-195 AC3).

Two stores are migrated through ``migrate_store`` (so the real store tree, including the
KAN-70 catalogue revision, runs) and every read and write goes through ``open_store_session``,
the only door to a store database. Rows written in store A must never be visible or
writable from store B, and the two stores' migrations must be independent.

Limits: this proves database-level separation (one database per store), not role-level
separation; both databases share one server login in the test setup. No product route
exists yet, so there is no route-level cross-store test; the first route that opens a store
session for catalogue data must add one.

Skipped when ``TEST_DATABASE_URL`` is unset.
"""

from dataclasses import dataclass
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.ids import new_id
from app.services.store_migrations import migrate_store
from app.services.store_sessions import open_store_session
from tests.pg_scaffold import TEST_DATABASE_URL, url_for
from tests.services.test_store_catalogue_schema_e2e import (
    CATALOGUE_TABLES,
    LINK,
    option,
    product,
    variant,
    violated_constraint,
)
from tests.services.test_store_migrations_e2e import (  # noqa: F401  (fixtures)
    World,
    server,
    world,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

CATALOGUE_HEAD = "0002"
SLUG = "tee"
SKU = "TEE-1"
TABLES = sorted(CATALOGUE_TABLES)


@dataclass(frozen=True)
class Catalogue:
    """Ids of one fully linked product graph seeded in a store."""

    product_id: str
    variant_id: str
    option_id: str
    value_id: str

    def params(self) -> dict[str, str]:
        return {
            "p": self.product_id,
            "v": self.variant_id,
            "o": self.option_id,
            "x": self.value_id,
        }


@dataclass(frozen=True)
class TwoStores:
    w: World
    store_a: str
    store_b: str
    database_a: str
    database_b: str


async def seed(w: World, store_id: str, slug: str = SLUG, sku: str = SKU) -> Catalogue:
    """One product with a variant, an option, a value and the variant-value link."""
    async with open_store_session(store_id, w.provider) as session:
        conn = await session.connection()
        product_id = await product(conn, slug)
        variant_id = await variant(conn, product_id, sku)
        option_id, (value_id,) = await option(conn, product_id, "Size", "M")
        await conn.execute(
            LINK,
            {"i": variant_id, "o": option_id, "v": value_id, "p": product_id},
        )
        await session.commit()
    return Catalogue(product_id, variant_id, option_id, value_id)


async def scalar(w: World, store_id: str, sql: str, **params: object) -> Any:
    async with open_store_session(store_id, w.provider) as session:
        return (await session.execute(text(sql), params)).scalar_one()


async def counts(w: World, store_id: str) -> dict[str, int]:
    async with open_store_session(store_id, w.provider) as session:
        return {
            table: (
                await session.execute(text(f"SELECT count(*) FROM {table}"))
            ).scalar_one()
            for table in TABLES
        }


async def snapshot(w: World, store_id: str) -> dict[str, list[Any]]:
    """Every catalogue row of the store, ordered, for before/after equality checks."""
    async with open_store_session(store_id, w.provider) as session:
        return {
            table: [
                tuple(row)
                for row in await session.execute(
                    text(f"SELECT * FROM {table} ORDER BY 1, 2")
                )
            ]
            for table in TABLES
        }


async def migration_state(w: World, store_id: str, database: str) -> tuple[Any, int]:
    return await w.stamped_revision(database), await w.schema_version(store_id)


def one_each() -> dict[str, int]:
    return dict.fromkeys(TABLES, 1)


def none_each() -> dict[str, int]:
    return dict.fromkeys(TABLES, 0)


@pytest.fixture
async def unmigrated(world: World) -> TwoStores:  # noqa: F811
    database_a = await world.store_database("ca")
    database_b = await world.store_database("cb")
    store_a = await world.add_store(url_for(database_a))
    store_b = await world.add_store(url_for(database_b))
    return TwoStores(world, store_a, store_b, database_a, database_b)


@pytest.fixture
async def stores(unmigrated: TwoStores) -> TwoStores:
    await migrate_store(unmigrated.store_a, unmigrated.w.provider)
    await migrate_store(unmigrated.store_b, unmigrated.w.provider)
    return unmigrated


async def test_migrating_one_store_leaves_the_other_untouched(
    unmigrated: TwoStores,
) -> None:
    s = unmigrated

    await migrate_store(s.store_a, s.w.provider)

    assert await migration_state(s.w, s.store_a, s.database_a) == (
        CATALOGUE_HEAD,
        int(CATALOGUE_HEAD),
    )
    assert await migration_state(s.w, s.store_b, s.database_b) == (None, 0)
    other = create_async_engine(url_for(s.database_b))
    try:
        async with other.connect() as connection:
            found = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:n)"
                    ),
                    {"n": TABLES},
                )
            ).scalar_one()
    finally:
        await other.dispose()
    assert found == 0

    await migrate_store(s.store_b, s.w.provider)

    assert await migration_state(s.w, s.store_a, s.database_a) == (
        CATALOGUE_HEAD,
        int(CATALOGUE_HEAD),
    )
    assert await counts(s.w, s.store_b) == none_each()


async def test_both_stores_have_the_catalogue_tables_at_head(stores: TwoStores) -> None:
    for store_id, database in (
        (stores.store_a, stores.database_a),
        (stores.store_b, stores.database_b),
    ):
        assert await migration_state(stores.w, store_id, database) == (
            CATALOGUE_HEAD,
            int(CATALOGUE_HEAD),
        )
        assert await counts(stores.w, store_id) == none_each()


async def test_a_store_added_later_is_migrated_without_touching_the_others(
    stores: TwoStores,
) -> None:
    w = stores.w
    seeded = await seed(w, stores.store_a)
    state_a = await migration_state(w, stores.store_a, stores.database_a)
    state_b = await migration_state(w, stores.store_b, stores.database_b)
    late_database = await w.store_database("cc")
    late = await w.add_store(url_for(late_database))
    assert await migration_state(w, late, late_database) == (None, 0)

    await migrate_store(late, w.provider)

    assert await migration_state(w, late, late_database) == (
        CATALOGUE_HEAD,
        int(CATALOGUE_HEAD),
    )
    assert await counts(w, late) == none_each()
    assert await counts(w, stores.store_b) == none_each()
    assert await migration_state(w, stores.store_a, stores.database_a) == state_a
    assert await migration_state(w, stores.store_b, stores.database_b) == state_b
    assert (
        await scalar(w, stores.store_a, "SELECT id FROM products") == seeded.product_id
    )


async def test_rows_written_in_one_store_are_invisible_in_the_other(
    stores: TwoStores,
) -> None:
    w = stores.w
    seeded = await seed(w, stores.store_a)

    assert await counts(w, stores.store_a) == one_each()  # positive control
    assert await counts(w, stores.store_b) == none_each()
    for table, column, value in (
        ("products", "id", seeded.product_id),
        ("variants", "id", seeded.variant_id),
        ("product_options", "id", seeded.option_id),
        ("product_option_values", "id", seeded.value_id),
        ("variant_option_values", "variant_id", seeded.variant_id),
    ):
        sql = f"SELECT count(*) FROM {table} WHERE {column} = :v"
        assert await scalar(w, stores.store_a, sql, v=value) == 1, table
        assert await scalar(w, stores.store_b, sql, v=value) == 0, table


async def test_the_same_slug_and_sku_can_live_in_both_stores_but_not_twice_in_one(
    stores: TwoStores,
) -> None:
    w = stores.w
    in_a = await seed(w, stores.store_a)

    in_b = await seed(w, stores.store_b)  # same slug and sku: uniqueness is per store

    assert in_a.product_id != in_b.product_id
    assert await counts(w, stores.store_a) == one_each()
    assert await counts(w, stores.store_b) == one_each()
    # negative control: within one store the same slug is rejected
    async with open_store_session(stores.store_b, w.provider) as session:
        with pytest.raises(IntegrityError) as caught:
            await session.execute(
                text("INSERT INTO products (id, title, slug) VALUES (:i, 'T', :s)"),
                {"i": new_id(), "s": SLUG},
            )
        assert violated_constraint(caught.value) == "uq_products_slug"


WRITES = (
    "UPDATE products SET title = 'hijacked' WHERE id = :p",
    "UPDATE variants SET price_minor = 1 WHERE id = :v",
    "UPDATE product_options SET name = 'hijacked' WHERE id = :o",
    "UPDATE product_option_values SET value = 'hijacked' WHERE id = :x",
    "DELETE FROM variant_option_values WHERE variant_id = :v",
    "DELETE FROM product_option_values WHERE id = :x",
    "DELETE FROM product_options WHERE id = :o",
    "DELETE FROM variants WHERE id = :v",
    "DELETE FROM products WHERE id = :p",
)


async def rowcounts(
    w: World, store_id: str, ids: dict[str, str], commit: bool
) -> set[int]:
    seen: set[int] = set()
    async with open_store_session(store_id, w.provider) as session:
        for sql in WRITES:
            result = cast("CursorResult[Any]", await session.execute(text(sql), ids))
            seen.add(result.rowcount)
        if commit:
            await session.commit()
    return seen


async def test_writes_by_id_through_one_store_never_reach_the_other(
    stores: TwoStores,
) -> None:
    w = stores.w
    in_a = await seed(w, stores.store_a)
    await seed(w, stores.store_b, slug="own", sku="OWN-1")  # B is populated too
    before_a = await snapshot(w, stores.store_a)
    before_b = await snapshot(w, stores.store_b)

    through_b = await rowcounts(w, stores.store_b, in_a.params(), commit=True)

    assert through_b == {0}
    assert await snapshot(w, stores.store_a) == before_a
    assert await snapshot(w, stores.store_b) == before_b
    # positive control: the same statements do hit exactly one row in A (rolled back)
    assert await rowcounts(w, stores.store_a, in_a.params(), commit=False) == {1}
    assert await snapshot(w, stores.store_a) == before_a


async def test_the_same_id_in_both_stores_is_addressed_per_database(
    stores: TwoStores,
) -> None:
    w = stores.w
    shared = new_id()
    for store_id in (stores.store_a, stores.store_b):
        async with open_store_session(store_id, w.provider) as session:
            await session.execute(
                text("INSERT INTO products (id, title, slug) VALUES (:i, 'T', :s)"),
                {"i": shared, "s": f"p-{store_id[:8].lower()}"},
            )
            await session.commit()

    async with open_store_session(stores.store_b, w.provider) as session:
        await session.execute(
            text("UPDATE products SET title = 'changed' WHERE id = :i"), {"i": shared}
        )
        await session.commit()

    sql = "SELECT title FROM products WHERE id = :i"
    assert await scalar(w, stores.store_a, sql, i=shared) == "T"
    assert await scalar(w, stores.store_b, sql, i=shared) == "changed"


async def test_store_b_cannot_attach_rows_to_store_a_catalogue_ids(
    stores: TwoStores,
) -> None:
    w = stores.w
    in_a = await seed(w, stores.store_a)
    immediate = (
        (
            (
                "INSERT INTO variants (id, product_id, sku, price_minor) "
                "VALUES (:i, :p, 'X', 1)"
            ),
            {"i": new_id(), "p": in_a.product_id},
            ("fk_variants_product"),
        ),
        (
            ("INSERT INTO product_options (id, product_id, name) VALUES (:i, :p, 'N')"),
            {"i": new_id(), "p": in_a.product_id},
            ("fk_product_options_product"),
        ),
        (
            (
                "INSERT INTO product_option_values (id, option_id, value) "
                "VALUES (:i, :o, 'v')"
            ),
            {"i": new_id(), "o": in_a.option_id},
            ("fk_product_option_values_option"),
        ),
        (
            (
                "INSERT INTO variant_option_values "
                "(variant_id, option_id, option_value_id, product_id) "
                "VALUES (:v, :o, :x, :p)"
            ),
            in_a.params(),
            ("fk_variant_option_values_variant_product"),
        ),
    )

    for sql, params, constraint in immediate:
        async with open_store_session(stores.store_b, w.provider) as session:
            with pytest.raises(IntegrityError) as caught:
                await session.execute(text(sql), params)
            assert violated_constraint(caught.value) == constraint

    assert await counts(w, stores.store_b) == none_each()
    assert await counts(w, stores.store_a) == one_each()


async def test_store_b_cannot_link_its_own_variant_to_store_a_option_ids(
    stores: TwoStores,
) -> None:
    """The option and value foreign keys are deferred: they fail at commit."""
    w = stores.w
    in_a = await seed(w, stores.store_a)
    in_b = await seed(w, stores.store_b, slug="own", sku="OWN-1")
    before_b = await snapshot(w, stores.store_b)

    async with open_store_session(stores.store_b, w.provider) as session:
        await session.execute(
            text("DELETE FROM variant_option_values WHERE variant_id = :v"),
            {"v": in_b.variant_id},
        )
        await session.execute(
            LINK,
            {
                "i": in_b.variant_id,
                "o": in_a.option_id,
                "v": in_a.value_id,
                "p": in_b.product_id,
            },
        )
        with pytest.raises(IntegrityError) as caught:
            await session.commit()
        assert violated_constraint(caught.value) == (
            "fk_variant_option_values_option_product"
        )

    assert await snapshot(w, stores.store_b) == before_b


async def test_a_delete_cascade_in_one_store_leaves_the_other_graph_whole(
    stores: TwoStores,
) -> None:
    w = stores.w
    await seed(w, stores.store_a)
    await seed(w, stores.store_b)

    async with open_store_session(stores.store_b, w.provider) as session:
        await session.execute(text("DELETE FROM products"))
        await session.commit()

    assert await counts(w, stores.store_b) == none_each()
    assert await counts(w, stores.store_a) == one_each()


async def test_each_catalogue_session_is_bound_to_its_own_database(
    stores: TwoStores,
) -> None:
    w = stores.w

    assert (
        await scalar(w, stores.store_a, "SELECT current_database()")
        == stores.database_a
    )
    assert (
        await scalar(w, stores.store_b, "SELECT current_database()")
        == stores.database_b
    )
    assert stores.database_a != stores.database_b
    for platform_table in ("stores", "organizations", "users", "memberships"):
        found = await scalar(
            w, stores.store_a, "SELECT to_regclass(:t)", t=platform_table
        )
        assert found is None, platform_table
