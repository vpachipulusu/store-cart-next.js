"""Store migration 0011 (order refunds, ``stock_taken``, KAN-80) against a real Postgres.

Lines written before 0011 survive the upgrade with the new counters at 0, the CHECKs,
unique indexes and RESTRICT keys hold, and the downgrade back to 0010 is clean. Reuses the
fixtures of the store migration suite; skipped when ``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

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
async def at_0010(
    world: World,  # noqa: F811
) -> AsyncIterator[tuple[World, str, AsyncEngine]]:
    database = await world.store_database("ref11")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_to("0010", down=True))
        yield world, database, engine
    finally:
        await engine.dispose()


async def _order_with_line(connection: AsyncConnection) -> tuple[str, str]:
    order_id, item_id = new_id(), new_id()
    await connection.execute(
        text(
            "INSERT INTO orders (id, status, currency, subtotal_minor, tax_minor,"
            " total_minor) VALUES (:id, 'paid', 'GBP', 300, 0, 300)"
        ),
        {"id": order_id},
    )
    await connection.execute(
        text(
            "INSERT INTO order_items (id, order_id, product_name, sku, unit_price_minor,"
            " quantity, tax_rate_bps, tax_minor)"
            " VALUES (:id, :o, 'Tee', 'TEE', 100, 3, 0, 0)"
        ),
        {"id": item_id, "o": order_id},
    )
    return order_id, item_id


async def _refund(connection: AsyncConnection, order_id: str, **over: Any) -> str:
    values: dict[str, Any] = {
        "id": new_id(),
        "o": order_id,
        "amount": 100,
        "status": "pending",
        "restock": False,
        "restocked": False,  # whether restocked_at is set
        "stripe": None,
        "key": None,
        "fp": "0" * 64 if over.get("key") else None,
        **over,
    }
    await connection.execute(
        text(
            "INSERT INTO order_refunds (id, order_id, amount_minor, currency, status,"
            " restock, restocked_at, stripe_refund_id, client_key, client_fingerprint)"
            " VALUES (:id, :o, :amount, 'GBP', :status, :restock,"
            " CASE WHEN :restocked THEN now() END, :stripe, :key, :fp)"
        ),
        values,
    )
    return str(values["id"])


async def test_lines_from_before_0011_survive_with_zero_counters(
    at_0010: tuple[World, str, AsyncEngine],
) -> None:
    _, _, engine = at_0010
    async with engine.begin() as connection:
        order_id, _ = await _order_with_line(connection)

    async with engine.begin() as connection:
        await connection.run_sync(_to("0011", down=False))
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT stock_taken, restocked_quantity FROM order_items"
                    " WHERE order_id = :o"
                ),
                {"o": order_id},
            )
        ).one()

    assert tuple(row) == (0, 0)


@pytest.fixture
async def at_0011(
    at_0010: tuple[World, str, AsyncEngine],
) -> AsyncIterator[tuple[AsyncEngine, str, str]]:
    _, _, engine = at_0010
    async with engine.begin() as connection:
        await connection.run_sync(_to("0011", down=False))
    async with engine.begin() as connection:
        order_id, item_id = await _order_with_line(connection)
    yield engine, order_id, item_id


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE order_items SET stock_taken = 4",  # more than the quantity
        "UPDATE order_items SET restocked_quantity = 1",  # more than was taken
        "UPDATE order_items SET stock_taken = -1",
    ],
)
async def test_stock_counters_are_bounded(
    at_0011: tuple[AsyncEngine, str, str], sql: str
) -> None:
    engine, _, _ = at_0011

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(sql))


@pytest.mark.parametrize(
    "over",
    [
        {"amount": 0},
        {"status": "done"},
        {"restocked": True},  # restocked_at needs restock and a succeeded refund
        {"key": ""},
        {"stripe": ""},
    ],
)
async def test_refund_rows_are_checked(
    at_0011: tuple[AsyncEngine, str, str], over: dict[str, Any]
) -> None:
    engine, order_id, _ = at_0011

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await _refund(connection, order_id, **over)


async def test_a_stripe_refund_id_and_a_client_key_belong_to_one_refund(
    at_0011: tuple[AsyncEngine, str, str],
) -> None:
    engine, order_id, _ = at_0011
    async with engine.begin() as connection:
        await _refund(connection, order_id, stripe="re_1", key="k")
        await _refund(connection, order_id)  # no id, no key: any number of these
        await _refund(connection, order_id)

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await _refund(connection, order_id, stripe="re_1")
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await _refund(connection, order_id, key="k")
    async with engine.begin() as connection:  # the same key on another order is fine
        second_order, _ = await _order_with_line(connection)
        await _refund(connection, second_order, key="k")


async def test_an_order_or_line_with_refunds_cannot_be_deleted(
    at_0011: tuple[AsyncEngine, str, str],
) -> None:
    engine, order_id, item_id = at_0011
    async with engine.begin() as connection:
        refund_id = await _refund(connection, order_id)
        await connection.execute(
            text(
                "INSERT INTO order_refund_items (refund_id, order_item_id, quantity)"
                " VALUES (:r, :i, 1)"
            ),
            {"r": refund_id, "i": item_id},
        )

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM orders WHERE id = :o"), {"o": order_id}
            )
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM order_items WHERE id = :i"), {"i": item_id}
            )


async def test_downgrade_is_clean_and_keeps_orders(
    at_0011: tuple[AsyncEngine, str, str],
) -> None:
    engine, order_id, _ = at_0011

    async with engine.begin() as connection:
        await connection.run_sync(_to("0010", down=True))
    async with engine.connect() as connection:
        left_over = await connection.scalar(
            text(
                "SELECT (SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'order_items'"
                " AND column_name IN ('stock_taken', 'restocked_quantity'))"
                " + (SELECT count(*) FROM information_schema.tables"
                " WHERE table_name IN ('order_refunds', 'order_refund_items'))"
            )
        )
        orders = await connection.scalar(
            text("SELECT count(*) FROM orders WHERE id = :o"), {"o": order_id}
        )
    async with engine.begin() as connection:
        await connection.run_sync(_to("head", down=False))  # and up again

    assert (left_over, orders) == (0, 1)


@pytest.mark.parametrize(
    "over",
    [
        {"key": "k", "fp": None},  # a key needs its fingerprint
        {"key": None, "fp": "0" * 64},  # and a fingerprint needs its key
        {"key": "k", "fp": "short"},
    ],
)
async def test_a_client_key_and_its_fingerprint_go_together(
    at_0011: tuple[AsyncEngine, str, str], over: dict[str, Any]
) -> None:
    engine, order_id, _ = at_0011

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await _refund(connection, order_id, **over)
