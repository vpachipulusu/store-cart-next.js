"""Stock decrement when an order is paid, against a real Postgres (KAN-72).

``mark_checkout_paid`` moves the order to ``paid`` and takes the stock in the same
transaction: a retry changes nothing, an unpaid or mismatched session never touches stock,
and two orders racing for the last unit give exactly one decrement and one ``oversold``
flag. Skipped when ``TEST_DATABASE_URL`` is unset.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.services import store_orders
from app.services.store_checkout import confirm_checkout_payment
from app.services.store_migrations import migrate_store
from app.services.store_orders import (
    OrderLineInput,
    OrderStatus,
    PaymentOutcome,
    create_order,
    mark_checkout_paid,
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

PRICE = 1000


@dataclass(frozen=True)
class Shop:
    store_id: str
    scarce: str  # one unit
    plenty: str  # five units
    spare: str  # five units


async def _variant(session: AsyncSession, product_id: str, sku: str, stock: int) -> str:
    variant_id = new_id()
    await session.execute(
        text(
            "INSERT INTO variants (id, product_id, sku, price_minor, stock) "
            "VALUES (:v, :p, :sku, :price, :stock)"
        ),
        {"v": variant_id, "p": product_id, "sku": sku, "price": PRICE, "stock": stock},
    )
    return variant_id


@pytest.fixture
async def shop(world: World) -> AsyncIterator[Shop]:  # noqa: F811
    database = await world.store_database("inv")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    async with open_store_session(store_id, world.provider) as session:
        product_id = new_id()
        await session.execute(
            text(
                "INSERT INTO products (id, title, slug, status) "
                "VALUES (:p, 'Tee', 'tee', 'active')"
            ),
            {"p": product_id},
        )
        scarce = await _variant(session, product_id, "TEE-A", 1)
        plenty = await _variant(session, product_id, "TEE-B", 5)
        spare = await _variant(session, product_id, "TEE-C", 5)
        await session.commit()
    yield Shop(store_id, scarce, plenty, spare)


async def _order(
    world: World,  # noqa: F811
    shop: Shop,
    lines: list[tuple[str, int]],
) -> tuple[str, int]:
    """A pending order for the lines; returns its id and total."""
    async with open_store_session(shop.store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=v, quantity=q) for v, q in lines],
        )
        await session.commit()
    return order.id, order.total_minor


async def _pay(
    world: World,  # noqa: F811
    shop: Shop,
    order: tuple[str, int],
    *,
    amount: int | None = None,
) -> PaymentOutcome:
    order_id, total = order
    async with open_store_session(shop.store_id, world.provider) as session:
        outcome = await mark_checkout_paid(
            session,
            order_id=order_id,
            session_id=f"cs_{order_id}",
            payment_intent_id=None,
            amount_minor=total if amount is None else amount,
            currency="GBP",
        )
        await session.commit()
    return outcome


async def _scalar(world: World, shop: Shop, sql: str, **params: str) -> object:  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        return await session.scalar(text(sql), params)


async def _stock(world: World, shop: Shop, variant_id: str) -> int:  # noqa: F811
    value = await _scalar(
        world, shop, "SELECT stock FROM variants WHERE id = :v", v=variant_id
    )
    assert isinstance(value, int)
    return value


async def _oversold(world: World, shop: Shop, order_id: str) -> bool:  # noqa: F811
    value = await _scalar(
        world, shop, "SELECT oversold FROM orders WHERE id = :o", o=order_id
    )
    assert isinstance(value, bool)
    return value


async def test_paying_an_order_takes_its_quantities_from_stock(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.plenty, 2)])

    outcome = await _pay(world, shop, order)

    assert outcome is PaymentOutcome.PAID
    assert await _stock(world, shop, shop.plenty) == 3
    assert not await _oversold(world, shop, order[0])


async def test_a_pending_order_does_not_touch_stock(
    world: World,  # noqa: F811
    shop: Shop,
):
    await _order(world, shop, [(shop.plenty, 2)])

    assert await _stock(world, shop, shop.plenty) == 5


async def test_a_retried_delivery_does_not_take_stock_twice(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.plenty, 2)])

    first = await _pay(world, shop, order)
    second = await _pay(world, shop, order)

    assert (first, second) == (PaymentOutcome.PAID, PaymentOutcome.ALREADY_PAID)
    assert await _stock(world, shop, shop.plenty) == 3


async def test_a_mismatched_payment_leaves_stock_alone(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.plenty, 2)])

    outcome = await _pay(world, shop, order, amount=order[1] - 1)

    assert outcome is PaymentOutcome.MISMATCH
    assert await _stock(world, shop, shop.plenty) == 5


async def test_a_short_line_flags_the_order_but_keeps_it_paid(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.scarce, 1), (shop.plenty, 2)])
    # Another sale took the last unit after this order was priced.
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(
            text("UPDATE variants SET stock = 0 WHERE id = :v"), {"v": shop.scarce}
        )
        await session.commit()

    outcome = await _pay(world, shop, order)

    assert outcome is PaymentOutcome.PAID
    assert await _oversold(world, shop, order[0])
    assert await _stock(world, shop, shop.scarce) == 0  # never below zero
    assert await _stock(world, shop, shop.plenty) == 3  # the other line is still taken
    status = await _scalar(
        world, shop, "SELECT status FROM orders WHERE id = :o", o=order[0]
    )
    assert status == "paid"


async def test_a_line_whose_variant_was_deleted_flags_the_order(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.scarce, 1)])
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(
            text("UPDATE order_items SET variant_id = NULL WHERE order_id = :o"),
            {"o": order[0]},
        )
        await session.commit()

    outcome = await _pay(world, shop, order)

    assert outcome is PaymentOutcome.PAID
    assert await _oversold(world, shop, order[0])
    assert await _stock(world, shop, shop.scarce) == 1


async def test_two_orders_racing_for_the_last_unit_give_one_sale_and_one_flag(
    world: World,  # noqa: F811
    shop: Shop,
):
    first = await _order(world, shop, [(shop.scarce, 1)])
    second = await _order(
        world, shop, [(shop.scarce, 1)]
    )  # priced while a unit remained

    outcomes = await asyncio.gather(_pay(world, shop, first), _pay(world, shop, second))

    assert outcomes == [PaymentOutcome.PAID, PaymentOutcome.PAID]
    assert await _stock(world, shop, shop.scarce) == 0
    flags = [
        await _oversold(world, shop, first[0]),
        await _oversold(world, shop, second[0]),
    ]
    assert sorted(flags) == [False, True]


async def test_many_orders_racing_never_take_stock_below_zero(
    world: World,  # noqa: F811
    shop: Shop,
):
    orders = [await _order(world, shop, [(shop.plenty, 2)]) for _ in range(6)]

    await asyncio.gather(*(_pay(world, shop, order) for order in orders))

    assert (
        await _stock(world, shop, shop.plenty) == 1
    )  # five units: two orders of two fit
    flags = [await _oversold(world, shop, order[0]) for order in orders]
    assert (flags.count(False), flags.count(True)) == (2, 4)


async def test_cancelling_a_pending_order_never_touches_stock(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.plenty, 2)])
    async with open_store_session(shop.store_id, world.provider) as session:
        await transition_order(session, order[0], OrderStatus.CANCELLED)
        await session.commit()

    assert await _stock(world, shop, shop.plenty) == 5


async def test_concurrent_deliveries_of_one_order_take_stock_once(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.plenty, 2)])

    outcomes = await asyncio.gather(_pay(world, shop, order), _pay(world, shop, order))

    assert sorted(outcome.value for outcome in outcomes) == ["already_paid", "paid"]
    assert await _stock(world, shop, shop.plenty) == 3


async def test_a_rolled_back_payment_leaves_the_order_pending_and_stock_untaken(
    world: World,  # noqa: F811
    shop: Shop,
):
    order_id, total = await _order(world, shop, [(shop.plenty, 2)])
    async with open_store_session(shop.store_id, world.provider) as session:
        await mark_checkout_paid(
            session,
            order_id=order_id,
            session_id="cs_rolled_back",
            payment_intent_id=None,
            amount_minor=total,
            currency="GBP",
        )
        await session.rollback()

    status = await _scalar(
        world, shop, "SELECT status FROM orders WHERE id = :o", o=order_id
    )
    assert status == "pending"
    assert await _stock(world, shop, shop.plenty) == 5


async def test_orders_with_the_same_variants_in_opposite_order_do_not_deadlock(
    world: World,  # noqa: F811
    shop: Shop,
):
    forward = await _order(world, shop, [(shop.plenty, 1), (shop.spare, 1)])
    backward = await _order(world, shop, [(shop.spare, 1), (shop.plenty, 1)])

    outcomes = await asyncio.gather(
        *(_pay(world, shop, order) for order in (forward, backward) * 3)
    )

    assert set(outcomes) == {PaymentOutcome.PAID, PaymentOutcome.ALREADY_PAID}
    assert await _stock(world, shop, shop.plenty) == 3
    assert await _stock(world, shop, shop.spare) == 3


async def test_a_raced_multi_line_loser_still_takes_its_covered_line(
    world: World,  # noqa: F811
    shop: Shop,
):
    winner = await _order(world, shop, [(shop.scarce, 1)])
    loser = await _order(world, shop, [(shop.scarce, 1), (shop.plenty, 2)])

    await _pay(world, shop, winner)
    await _pay(world, shop, loser)

    assert not await _oversold(world, shop, winner[0])
    assert await _oversold(world, shop, loser[0])
    assert await _stock(world, shop, shop.plenty) == 3


async def _confirm(world: World, shop: Shop, order: tuple[str, int]) -> None:  # noqa: F811
    order_id, total = order
    async with open_store_session(shop.store_id, world.provider) as session:
        await confirm_checkout_payment(
            session,
            {
                "id": f"cs_{order_id}",
                "payment_status": "paid",
                "metadata": {"order_id": order_id},
                "amount_total": total,
                "currency": "gbp",
                "payment_intent": None,
            },
        )
        await session.commit()


async def test_the_payment_event_takes_stock_and_a_redelivery_does_not(
    world: World,  # noqa: F811
    shop: Shop,
):
    order = await _order(world, shop, [(shop.plenty, 2)])

    await _confirm(world, shop, order)
    await _confirm(world, shop, order)

    assert await _stock(world, shop, shop.plenty) == 3
    assert not await _oversold(world, shop, order[0])


async def test_the_payment_event_on_a_sold_out_variant_keeps_the_order_paid_and_reports_it(
    world: World,  # noqa: F811
    shop: Shop,
    monkeypatch: pytest.MonkeyPatch,
):
    reported: list[BaseException] = []
    monkeypatch.setattr(store_orders, "report_exception", reported.append)
    order = await _order(world, shop, [(shop.scarce, 1)])
    clean = await _order(world, shop, [(shop.plenty, 1)])
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(
            text("UPDATE variants SET stock = 0 WHERE id = :v"), {"v": shop.scarce}
        )
        await session.commit()

    await _confirm(world, shop, order)
    await _confirm(world, shop, clean)

    status = await _scalar(
        world, shop, "SELECT status FROM orders WHERE id = :o", o=order[0]
    )
    assert (status, await _oversold(world, shop, order[0])) == ("paid", True)
    assert [type(error) for error in reported] == [store_orders.OversoldOrder]
