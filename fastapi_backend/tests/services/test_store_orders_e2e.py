"""Order service against two real store databases, through ``open_store_session`` (KAN-78).

Covers the purchase snapshot (name, SKU, variant label, price, tax), the atomic status
transition and tenant isolation: an order id from store A is unknown to store B. Skipped
when ``TEST_DATABASE_URL`` is unset.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.services.store_migrations import migrate_store
from app.services.store_orders import (
    ALLOWED_TRANSITIONS,
    MAX_MINOR,
    InvalidOrder,
    InvalidOrderTransition,
    OrderLineInput,
    OrderNotFound,
    OrderStatus,
    create_order,
    transition_order,
)
from app.services.store_sessions import open_store_session
from tests.pg_scaffold import TEST_DATABASE_URL, url_for
from tests.services.test_store_migrations_e2e import (  # noqa: F401  (fixtures)
    World,
    server,
    world,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


@dataclass(frozen=True)
class Shop:
    store_id: str
    product_id: str
    variant_id: str


async def seed(session: AsyncSession, *, status: str = "active") -> tuple[str, str]:
    product_id, variant_id, option_id, value_id = (new_id() for _ in range(4))
    await session.execute(
        text(
            "INSERT INTO products (id, title, slug, status) "
            "VALUES (:p, 'Tee', 'tee', :s)"
        ),
        {"p": product_id, "s": status},
    )
    await session.execute(
        text(
            "INSERT INTO variants (id, product_id, sku, price_minor) "
            "VALUES (:v, :p, 'TEE-L', 1999)"
        ),
        {"v": variant_id, "p": product_id},
    )
    await session.execute(
        text(
            "INSERT INTO product_options (id, product_id, name) VALUES (:o, :p, 'Size')"
        ),
        {"o": option_id, "p": product_id},
    )
    await session.execute(
        text(
            "INSERT INTO product_option_values (id, option_id, value) "
            "VALUES (:x, :o, 'Large')"
        ),
        {"x": value_id, "o": option_id},
    )
    await session.execute(
        text(
            "INSERT INTO variant_option_values "
            "(variant_id, option_id, option_value_id, product_id) "
            "VALUES (:v, :o, :x, :p)"
        ),
        {"v": variant_id, "o": option_id, "x": value_id, "p": product_id},
    )
    await session.commit()
    return product_id, variant_id


async def make_shop(world: World, name: str, *, status: str = "active") -> Shop:  # noqa: F811
    database = await world.store_database(name)
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    async with open_store_session(store_id, world.provider) as session:
        product_id, variant_id = await seed(session, status=status)
    return Shop(store_id, product_id, variant_id)


@pytest.fixture
async def shop(world: World) -> AsyncIterator[Shop]:  # noqa: F811
    yield await make_shop(world, "ord")


async def test_create_order_snapshots_name_price_and_tax(world: World, shop: Shop):  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=2000,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=2)],
        )
        await session.commit()

    assert order.status is OrderStatus.PENDING
    assert (order.subtotal_minor, order.tax_minor, order.total_minor) == (
        3998,
        800,
        4798,
    )
    line = order.items[0]
    assert (line.product_name, line.sku, line.variant_label) == (
        "Tee",
        "TEE-L",
        "Large",
    )
    assert (line.unit_price_minor, line.quantity) == (1999, 2)
    assert (line.tax_rate_bps, line.tax_minor) == (2000, 800)


async def test_snapshot_does_not_follow_later_catalogue_changes(
    world: World,  # noqa: F811
    shop: Shop,
):
    async with open_store_session(shop.store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=2000,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=1)],
        )
        await session.commit()
        await session.execute(
            text("UPDATE products SET title = 'Renamed' WHERE id = :p"),
            {"p": shop.product_id},
        )
        await session.execute(
            text("UPDATE variants SET price_minor = 9999, sku = 'X' WHERE id = :v"),
            {"v": shop.variant_id},
        )
        await session.commit()
        row = (
            await session.execute(
                text(
                    "SELECT product_name, sku, unit_price_minor, tax_minor "
                    "FROM order_items WHERE order_id = :o"
                ),
                {"o": order.id},
            )
        ).one()

    assert tuple(row) == ("Tee", "TEE-L", 1999, 400)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lines": []},
        {"currency": "gbp"},
        {"tax_rate_bps": -1},
        {"tax_rate_bps": 100_001},
    ],
)
async def test_create_order_rejects_invalid_input(
    world: World,  # noqa: F811
    shop: Shop,
    kwargs: dict[str, object],
):
    params: dict[str, object] = {
        "currency": "GBP",
        "tax_rate_bps": 0,
        "lines": [OrderLineInput(variant_id=shop.variant_id, quantity=1)],
        **kwargs,
    }
    async with open_store_session(shop.store_id, world.provider) as session:
        with pytest.raises(InvalidOrder):
            await create_order(session, **params)  # type: ignore[arg-type]


@pytest.mark.parametrize("quantity", [0, -1, 10_001])
async def test_create_order_rejects_a_bad_quantity(
    world: World,  # noqa: F811
    shop: Shop,
    quantity: int,
):
    async with open_store_session(shop.store_id, world.provider) as session:
        with pytest.raises(InvalidOrder):
            await create_order(
                session,
                currency="GBP",
                tax_rate_bps=0,
                lines=[OrderLineInput(variant_id=shop.variant_id, quantity=quantity)],
            )


async def test_create_order_rejects_an_unknown_variant(world: World, shop: Shop):  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        with pytest.raises(InvalidOrder):
            await create_order(
                session,
                currency="GBP",
                tax_rate_bps=0,
                lines=[OrderLineInput(variant_id="missing", quantity=1)],
            )


async def test_create_order_rejects_a_draft_product(world: World):  # noqa: F811
    draft = await make_shop(world, "draft", status="draft")
    async with open_store_session(draft.store_id, world.provider) as session:
        with pytest.raises(InvalidOrder):
            await create_order(
                session,
                currency="GBP",
                tax_rate_bps=0,
                lines=[OrderLineInput(variant_id=draft.variant_id, quantity=1)],
            )


async def test_a_rejected_line_leaves_no_order_rows(world: World, shop: Shop):  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        with pytest.raises(InvalidOrder):
            await create_order(
                session,
                currency="GBP",
                tax_rate_bps=0,
                lines=[
                    OrderLineInput(variant_id=shop.variant_id, quantity=1),
                    OrderLineInput(variant_id="missing", quantity=1),
                ],
            )
        await session.commit()
        count = (
            await session.execute(text("SELECT count(*) FROM orders"))
        ).scalar_one()

    assert count == 0


async def place(world: World, shop: Shop) -> str:  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=1)],
        )
        await session.commit()
    return order.id


async def stored_status(world: World, shop: Shop, order_id: str) -> str:  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        return (
            await session.execute(
                text("SELECT status FROM orders WHERE id = :o"), {"o": order_id}
            )
        ).scalar_one()


async def test_the_happy_path_walks_pending_paid_fulfilled(world: World, shop: Shop):  # noqa: F811
    order_id = await place(world, shop)

    async with open_store_session(shop.store_id, world.provider) as session:
        paid = await transition_order(session, order_id, OrderStatus.PAID)
        fulfilled = await transition_order(session, order_id, OrderStatus.FULFILLED)
        refunded = await transition_order(session, order_id, OrderStatus.REFUNDED)
        await session.commit()

    assert (paid, fulfilled, refunded) == (
        OrderStatus.PAID,
        OrderStatus.FULFILLED,
        OrderStatus.REFUNDED,
    )
    assert await stored_status(world, shop, order_id) == "refunded"


async def test_transition_bumps_updated_at(world: World, shop: Shop):  # noqa: F811
    order_id = await place(world, shop)

    async with open_store_session(shop.store_id, world.provider) as session:
        before = (
            await session.execute(
                text("SELECT updated_at FROM orders WHERE id = :o"), {"o": order_id}
            )
        ).scalar_one()
        await transition_order(session, order_id, OrderStatus.PAID)
        await session.commit()
        after = (
            await session.execute(
                text("SELECT updated_at FROM orders WHERE id = :o"), {"o": order_id}
            )
        ).scalar_one()

    assert after > before


async def test_an_invalid_move_is_rejected_and_the_status_is_unchanged(
    world: World,  # noqa: F811
    shop: Shop,
):
    order_id = await place(world, shop)

    async with open_store_session(shop.store_id, world.provider) as session:
        with pytest.raises(InvalidOrderTransition) as caught:
            await transition_order(session, order_id, OrderStatus.FULFILLED)

    assert caught.value.current is OrderStatus.PENDING
    assert await stored_status(world, shop, order_id) == "pending"


async def test_a_terminal_order_cannot_move(world: World, shop: Shop):  # noqa: F811
    order_id = await place(world, shop)
    async with open_store_session(shop.store_id, world.provider) as session:
        await transition_order(session, order_id, OrderStatus.CANCELLED)
        await session.commit()

    async with open_store_session(shop.store_id, world.provider) as session:
        with pytest.raises(InvalidOrderTransition):
            await transition_order(session, order_id, OrderStatus.PAID)


async def test_unknown_order_is_not_found(world: World, shop: Shop):  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        with pytest.raises(OrderNotFound):
            await transition_order(session, "missing", OrderStatus.PAID)


async def test_a_move_based_on_a_stale_status_is_rejected(world: World, shop: Shop):  # noqa: F811
    """The first caller cancels; the second's UPDATE no longer matches ``pending``."""
    order_id = await place(world, shop)

    async with (
        open_store_session(shop.store_id, world.provider) as first,
        open_store_session(shop.store_id, world.provider) as second,
    ):
        await transition_order(first, order_id, OrderStatus.CANCELLED)
        await first.commit()
        with pytest.raises(InvalidOrderTransition):
            await transition_order(second, order_id, OrderStatus.PAID)

    assert await stored_status(world, shop, order_id) == "cancelled"


async def test_an_order_of_one_store_is_unknown_to_another(world: World, shop: Shop):  # noqa: F811
    other = await make_shop(world, "other")
    order_id = await place(world, shop)

    async with open_store_session(other.store_id, world.provider) as session:
        with pytest.raises(OrderNotFound):
            await transition_order(session, order_id, OrderStatus.PAID)

    assert await stored_status(world, shop, order_id) == "pending"


async def test_a_variant_without_options_has_no_label_and_labels_follow_option_order(
    world: World,  # noqa: F811
    shop: Shop,
):
    async with open_store_session(shop.store_id, world.provider) as session:
        bare = new_id()
        await session.execute(
            text(
                "INSERT INTO variants (id, product_id, sku, price_minor) "
                "VALUES (:v, :p, 'BARE', 500)"
            ),
            {"v": bare, "p": shop.product_id},
        )
        await session.commit()
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=2000,
            lines=[
                OrderLineInput(variant_id=bare, quantity=1),
                OrderLineInput(variant_id=shop.variant_id, quantity=3),
            ],
        )

    labels = {item.sku: item.variant_label for item in order.items}
    assert labels == {"BARE": None, "TEE-L": "Large"}
    # Tax is computed per line and summed: 100 + round(1199.4).
    assert order.tax_minor == 100 + 1199
    assert order.subtotal_minor == 500 + 3 * 1999


async def test_the_persisted_rows_match_the_returned_order(
    world: World,  # noqa: F811
    shop: Shop,
):
    async with open_store_session(shop.store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="EUR",
            tax_rate_bps=1999,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=3)],
        )
        await session.commit()

    async with open_store_session(shop.store_id, world.provider) as session:
        header = (
            (
                await session.execute(
                    text("SELECT * FROM orders WHERE id = :o"), {"o": order.id}
                )
            )
            .mappings()
            .one()
        )
        line = (
            (
                await session.execute(
                    text("SELECT * FROM order_items WHERE order_id = :o"),
                    {"o": order.id},
                )
            )
            .mappings()
            .one()
        )
    item = order.items[0]
    assert (header["status"], header["currency"]) == ("pending", "EUR")
    assert (header["subtotal_minor"], header["tax_minor"], header["total_minor"]) == (
        order.subtotal_minor,
        order.tax_minor,
        order.total_minor,
    )
    assert {
        key: line[key] for key in line if key not in ("created_at", "updated_at")
    } == {
        "id": item.id,
        "order_id": order.id,
        "product_id": shop.product_id,
        "variant_id": shop.variant_id,
        "product_name": "Tee",
        "sku": "TEE-L",
        "variant_label": "Large",
        "unit_price_minor": 1999,
        "quantity": 3,
        "tax_rate_bps": 1999,
        "tax_minor": item.tax_minor,
    }


@pytest.mark.parametrize(
    ("current", "target"),
    [(c, t) for c in OrderStatus for t in OrderStatus],
)
async def test_the_database_applies_exactly_the_allowed_transitions(
    world: World,  # noqa: F811
    shop: Shop,
    current: OrderStatus,
    target: OrderStatus,
):
    order_id = await place(world, shop)
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(
            text("UPDATE orders SET status = :s WHERE id = :o"),
            {"s": current.value, "o": order_id},
        )
        await session.commit()

    async with open_store_session(shop.store_id, world.provider) as session:
        if target in ALLOWED_TRANSITIONS[current]:
            assert await transition_order(session, order_id, target) is target
            await session.commit()
            assert await stored_status(world, shop, order_id) == target.value
        else:
            with pytest.raises(InvalidOrderTransition) as caught:
                await transition_order(session, order_id, target)
            assert (caught.value.current, caught.value.target) == (current, target)
            assert await stored_status(world, shop, order_id) == current.value


async def test_an_order_total_beyond_the_bigint_range_is_rejected(
    world: World,  # noqa: F811
    shop: Shop,
):
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(
            text("UPDATE variants SET price_minor = :p WHERE id = :v"),
            {"p": 2**62, "v": shop.variant_id},
        )
        await session.commit()
        with pytest.raises(InvalidOrder, match="too large"):
            await create_order(
                session,
                currency="GBP",
                tax_rate_bps=0,
                lines=[OrderLineInput(variant_id=shop.variant_id, quantity=2)],
            )


async def move_and_commit(
    shop: Shop,
    world: World,  # noqa: F811
    order_id: str,
    target: OrderStatus,
) -> OrderStatus:
    """One caller in its own session: transition, then commit."""
    async with open_store_session(shop.store_id, world.provider) as session:
        result = await transition_order(session, order_id, target)
        await session.commit()
        return result


async def advance(world: World, shop: Shop, order_id: str, *path: OrderStatus) -> None:  # noqa: F811
    for target in path:
        await move_and_commit(shop, world, order_id, target)


@pytest.mark.parametrize("attempt", range(5))
@pytest.mark.parametrize(
    ("start", "first", "second"),
    [
        # Mutually exclusive moves: whichever commits first closes the other.
        ((OrderStatus.PAID,), OrderStatus.FULFILLED, OrderStatus.CANCELLED),
        ((OrderStatus.PAID,), OrderStatus.CANCELLED, OrderStatus.FULFILLED),
        ((), OrderStatus.PAID, OrderStatus.PAID),
        ((), OrderStatus.CANCELLED, OrderStatus.CANCELLED),
        ((OrderStatus.PAID,), OrderStatus.REFUNDED, OrderStatus.REFUNDED),
    ],
)
async def test_two_concurrent_conflicting_moves_exactly_one_wins(
    world: World,  # noqa: F811
    shop: Shop,
    start: tuple[OrderStatus, ...],
    first: OrderStatus,
    second: OrderStatus,
    attempt: int,
):
    order_id = await place(world, shop)
    await advance(world, shop, order_id, *start)

    results = await asyncio.gather(
        move_and_commit(shop, world, order_id, first),
        move_and_commit(shop, world, order_id, second),
        return_exceptions=True,
    )

    wins = [r for r in results if isinstance(r, OrderStatus)]
    losses = [r for r in results if isinstance(r, InvalidOrderTransition)]
    assert len(wins) == 1
    assert len(losses) == 1
    assert await stored_status(world, shop, order_id) == wins[0].value


@pytest.mark.parametrize("attempt", range(5))
async def test_concurrent_pay_and_cancel_end_in_a_legal_state(
    world: World,  # noqa: F811
    shop: Shop,
    attempt: int,
):
    """Paid then cancelled is a legal sequence, so both may win; cancelled-then-paid is not."""
    order_id = await place(world, shop)

    results = await asyncio.gather(
        move_and_commit(shop, world, order_id, OrderStatus.PAID),
        move_and_commit(shop, world, order_id, OrderStatus.CANCELLED),
        return_exceptions=True,
    )

    paid, cancelled = results
    assert cancelled is OrderStatus.CANCELLED  # pending/paid -> cancelled always works
    assert paid is OrderStatus.PAID or isinstance(paid, InvalidOrderTransition)
    assert await stored_status(world, shop, order_id) == "cancelled"


async def test_create_order_holds_the_catalogue_rows_until_it_commits(
    world: World,  # noqa: F811
    shop: Shop,
):
    """FOR SHARE: a price edit in another transaction waits for the order's transaction."""
    async with (
        open_store_session(shop.store_id, world.provider) as buyer,
        open_store_session(shop.store_id, world.provider) as editor,
    ):
        await create_order(
            buyer,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=1)],
        )
        await editor.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(DBAPIError, match="lock timeout|lock_timeout"):
            await editor.execute(
                text("UPDATE variants SET price_minor = 1 WHERE id = :v"),
                {"v": shop.variant_id},
            )
        await editor.rollback()

        await buyer.commit()
        await editor.execute(
            text("UPDATE variants SET price_minor = 1 WHERE id = :v"),
            {"v": shop.variant_id},
        )
        await editor.commit()


async def test_a_variant_of_another_store_is_not_available(
    world: World,  # noqa: F811
    shop: Shop,
):
    other = await make_shop(world, "foreign")

    async with open_store_session(other.store_id, world.provider) as session:
        with pytest.raises(InvalidOrder):
            await create_order(
                session,
                currency="GBP",
                tax_rate_bps=0,
                lines=[OrderLineInput(variant_id=shop.variant_id, quantity=1)],
            )
        await session.commit()
        count = (
            await session.execute(text("SELECT count(*) FROM orders"))
        ).scalar_one()
    assert count == 0


async def test_limits_are_accepted_at_their_boundaries(
    world: World,  # noqa: F811
    shop: Shop,
):
    async with open_store_session(shop.store_id, world.provider) as session:
        variant_ids = [shop.variant_id]
        for index in range(99):
            variant_id = new_id()
            await session.execute(
                text(
                    "INSERT INTO variants (id, product_id, sku, price_minor) "
                    "VALUES (:v, :p, :s, 1)"
                ),
                {"v": variant_id, "p": shop.product_id, "s": f"B-{index}"},
            )
            variant_ids.append(variant_id)
        await session.commit()

        hundred = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=100_000,
            lines=[OrderLineInput(variant_id=v, quantity=10_000) for v in variant_ids],
        )
        single = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=1)],
        )
        await session.commit()

    assert len(hundred.items) == 100
    assert hundred.total_minor == hundred.subtotal_minor + hundred.tax_minor
    assert single.tax_minor == 0


async def test_a_total_exactly_at_the_bigint_limit_is_accepted(
    world: World,  # noqa: F811
    shop: Shop,
):
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(
            text("UPDATE variants SET price_minor = :p WHERE id = :v"),
            {"p": MAX_MINOR, "v": shop.variant_id},
        )
        await session.commit()
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=1)],
        )
        await session.commit()

    assert order.total_minor == MAX_MINOR


async def test_a_two_option_label_follows_option_position(
    world: World,  # noqa: F811
):
    shop = await make_shop(world, "labels")
    async with open_store_session(shop.store_id, world.provider) as session:
        option_id, value_id = new_id(), new_id()
        # The seed's Size option sits at position 0; Colour goes after it.
        await session.execute(
            text(
                "INSERT INTO product_options (id, product_id, name, position) "
                "VALUES (:o, :p, 'Colour', 1)"
            ),
            {"o": option_id, "p": shop.product_id},
        )
        await session.execute(
            text(
                "INSERT INTO product_option_values (id, option_id, value) "
                "VALUES (:x, :o, 'Red')"
            ),
            {"x": value_id, "o": option_id},
        )
        await session.execute(
            text(
                "INSERT INTO variant_option_values "
                "(variant_id, option_id, option_value_id, product_id) "
                "VALUES (:v, :o, :x, :p)"
            ),
            {"v": shop.variant_id, "o": option_id, "x": value_id, "p": shop.product_id},
        )
        await session.commit()
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=shop.variant_id, quantity=1)],
        )

    assert order.items[0].variant_label == "Large / Red"
