"""Store migration 0012 (order emails, KAN-81) and the outbox SQL against a real Postgres.

The CHECKs, the unique outbox key and the cascade hold; the repository settles a row exactly
once; a store still at 0011 keeps its order change and only skips the email (SAVEPOINT); the
downgrade back to 0011 is clean. Reuses the fixtures of the store migration suite; skipped when
``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator, Callable

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.ids import new_id
from app.repositories.order_emails import OrderEmailsRepository
from app.services.order_email_job import (
    PAID_KINDS,
    pending_jobs,
    record_order_emails,
)
from app.services.order_email_templates import OrderEmailKind
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

STORE_ID = "abcdefgh12345678abcdefgh"


def _to(revision: str, *, down: bool) -> Callable[[Connection], None]:
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def run(connection: Connection) -> None:
        config.attributes["connection"] = connection
        (command.downgrade if down else command.upgrade)(config, revision)

    return run


@pytest.fixture
async def engine(world: World) -> AsyncIterator[AsyncEngine]:  # noqa: F811
    database = await world.store_database("mail12")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    built = create_async_engine(url_for(database))
    try:
        yield built
    finally:
        await built.dispose()


async def _order(engine: AsyncEngine, status: str = "paid") -> str:
    order_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO orders (id, status, currency, subtotal_minor, tax_minor,"
                " total_minor) VALUES (:id, :status, 'GBP', 300, 0, 300)"
            ),
            {"id": order_id, "status": status},
        )
    return order_id


async def _fails(engine: AsyncEngine, sql: str, **params: object) -> None:
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text(sql), params)


@pytest.mark.parametrize(
    "email", ["ab", "@example.com", "a" * 250 + "@x.com", "no-at-sign"]
)
async def test_an_impossible_customer_email_is_refused(
    engine: AsyncEngine, email: str
) -> None:
    order_id = await _order(engine)

    await _fails(
        engine,
        "UPDATE orders SET customer_email = :e WHERE id = :id",
        e=email,
        id=order_id,
    )


@pytest.mark.parametrize(
    ("kind", "subject", "body"),
    [
        ("invoice", "Hi", "Body"),
        ("order_confirmation", "", "Body"),
        ("order_confirmation", "a" * 201, "Body"),
        ("order_confirmation", "Hi\r\nBcc: x", "Body"),
        ("order_confirmation", "Hi\nthere", "Body"),
        ("order_confirmation", "Hi", ""),
        ("order_confirmation", "Hi", "b" * 10_001),
    ],
)
async def test_a_bad_store_template_is_refused(
    engine: AsyncEngine, kind: str, subject: str, body: str
) -> None:
    await _fails(
        engine,
        "INSERT INTO store_email_templates (kind, subject, body_text)"
        " VALUES (:k, :s, :b)",
        k=kind,
        s=subject,
        b=body,
    )


async def test_a_store_template_overrides_one_kind(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO store_email_templates (kind, subject, body_text)"
                " VALUES ('order_shipped', 'Shipped $order_id', 'On its way')"
            )
        )
    async with AsyncSession(engine) as session:
        repository = OrderEmailsRepository(session)
        shipped = await repository.template("order_shipped")
        confirmation = await repository.template("order_confirmation")

    assert shipped is not None and shipped.subject == "Shipped $order_id"
    assert confirmation is None


@pytest.mark.parametrize(
    ("columns", "values"),
    [
        ("kind", "'invoice'"),
        ("kind, status", "'order_shipped', 'queued'"),
        ("kind, attempts", "'order_shipped', -1"),
        ("kind, status", "'order_shipped', 'sent'"),  # sent without sent_at
        ("kind, sent_at", "'order_shipped', now()"),  # sent_at while pending
    ],
)
async def test_the_outbox_checks_hold(
    engine: AsyncEngine, columns: str, values: str
) -> None:
    order_id = await _order(engine)

    await _fails(
        engine,
        f"INSERT INTO order_emails (id, order_id, {columns})"
        f" VALUES (:id, :o, {values})",
        id=new_id(),
        o=order_id,
    )


async def test_an_outbox_row_needs_its_order(engine: AsyncEngine) -> None:
    await _fails(
        engine,
        "INSERT INTO order_emails (id, order_id, kind)"
        " VALUES (:id, 'nope', 'order_shipped')",
        id=new_id(),
    )


async def test_rows_are_written_once_per_kind_and_settle_once(
    engine: AsyncEngine,
) -> None:
    order_id = await _order(engine)

    async with AsyncSession(engine) as session:
        first = await record_order_emails(
            session,
            store_id=STORE_ID,
            order_id=order_id,
            kinds=PAID_KINDS,
            customer_email="shopper@example.com",
        )
        again = await record_order_emails(
            session, store_id=STORE_ID, order_id=order_id, kinds=PAID_KINDS
        )
        await session.commit()
        jobs = await pending_jobs(
            session, store_id=STORE_ID, order_id=order_id, kinds=PAID_KINDS
        )
        repository = OrderEmailsRepository(session)
        sent = await repository.finish(order_id, "order_confirmation", "sent")
        resent = await repository.finish(order_id, "order_confirmation", "failed")
        await repository.count_attempt(order_id, "new_order_alert")
        await session.commit()
        order = await repository.order(order_id)
        still_pending = await repository.pending_kinds(
            order_id, [kind.value for kind in PAID_KINDS]
        )

    assert first == list(PAID_KINDS)
    assert again == []
    assert sorted(job.kind.value for job in jobs) == [
        "new_order_alert",
        "order_confirmation",
    ]
    assert (sent, resent) == (True, False)
    assert order is not None and order.customer_email == "shopper@example.com"
    assert still_pending == ["new_order_alert"]
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT kind, status, attempts, sent_at IS NOT NULL FROM order_emails"
                    " WHERE order_id = :o ORDER BY kind"
                ),
                {"o": order_id},
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("new_order_alert", "pending", 1, False),
        ("order_confirmation", "sent", 0, True),
    ]


async def test_deleting_an_order_deletes_its_email_rows(engine: AsyncEngine) -> None:
    order_id = await _order(engine)
    async with AsyncSession(engine) as session:
        await record_order_emails(
            session,
            store_id=STORE_ID,
            order_id=order_id,
            kinds=(OrderEmailKind.ORDER_SHIPPED,),
        )
        await session.commit()

    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM orders WHERE id = :o"), {"o": order_id}
        )
        left = (
            await connection.execute(
                text("SELECT count(*) FROM order_emails WHERE order_id = :o"),
                {"o": order_id},
            )
        ).scalar_one()

    assert left == 0


async def test_a_store_at_0011_keeps_its_order_change_and_skips_the_email(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_to("0011", down=True))
    order_id = await _order(engine, status="pending")

    async with AsyncSession(engine) as session:
        await session.execute(
            text("UPDATE orders SET status = 'paid' WHERE id = :o"), {"o": order_id}
        )
        added = await record_order_emails(
            session,
            store_id=STORE_ID,
            order_id=order_id,
            kinds=PAID_KINDS,
            customer_email="shopper@example.com",
        )
        await session.commit()
        jobs = await pending_jobs(
            session, store_id=STORE_ID, order_id=order_id, kinds=PAID_KINDS
        )

    assert added == [] and jobs == []
    assert "order email skipped" in caplog.text
    async with engine.connect() as connection:
        status = (
            await connection.execute(
                text("SELECT status FROM orders WHERE id = :o"), {"o": order_id}
            )
        ).scalar_one()
    assert status == "paid"


async def test_the_downgrade_removes_everything_and_the_upgrade_is_repeatable(
    engine: AsyncEngine,
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_to("0011", down=True))
        tables = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables WHERE table_name"
                    " IN ('order_emails', 'store_email_templates')"
                )
            )
        ).scalar_one()
        column = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns"
                    " WHERE table_name = 'orders' AND column_name = 'customer_email'"
                )
            )
        ).scalar_one()
        await connection.run_sync(_to("0012", down=False))

    assert (tables, column) == (0, 0)
