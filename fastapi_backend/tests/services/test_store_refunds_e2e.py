"""Refund reservation, settlement and restock against a real Postgres (KAN-80).

A refund is reserved (``pending``) before Stripe is called and settled once by the Stripe
outcome. Restock is the merchant's per-refund choice (default off) and happens in the same
transaction as the settlement, so a replayed or concurrent settlement never restocks twice,
never returns a unit that was not taken (oversold lines), and skips deleted variants.
Skipped when ``TEST_DATABASE_URL`` is unset.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.services.store_migrations import migrate_store
from app.services.store_orders import (
    InvalidOrder,
    OrderLineInput,
    OrderNotFound,
    OrderStatus,
    create_order,
    fulfil_order,
    mark_checkout_paid,
    transition_order,
)
from app.services.store_refunds import (
    RefundLineInput,
    RefundNotAllowed,
    RefundOutcome,
    RefundPlan,
    reserve_refund,
    settle_refund,
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
TAX_BPS = 2000


@dataclass(frozen=True)
class Shop:
    store_id: str
    product_id: str
    a: str  # variant, stock 10
    b: str  # variant, stock 10
    scarce: str  # variant, stock 1


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
    database = await world.store_database("refund")
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
        a = await _variant(session, product_id, "TEE-A", 10)
        b = await _variant(session, product_id, "TEE-B", 10)
        scarce = await _variant(session, product_id, "TEE-C", 1)
        await session.commit()
    yield Shop(store_id, product_id, a, b, scarce)


async def _paid_order(
    world: World,  # noqa: F811
    shop: Shop,
    lines: list[tuple[str, int]],
    *,
    tax_bps: int = TAX_BPS,
    shipping: int = 0,
    included: bool = False,
    fulfilled: bool = False,
) -> str:
    """An order paid through ``mark_checkout_paid`` (so stock is taken); returns its id.

    ``shipping`` and ``included`` (prices include tax) mimic what checkout writes.
    """
    async with open_store_session(shop.store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=tax_bps,
            lines=[OrderLineInput(variant_id=v, quantity=q) for v, q in lines],
        )
        total = order.subtotal_minor + shipping + (0 if included else order.tax_minor)
        await session.execute(
            text(
                "UPDATE orders SET shipping_minor = :s, prices_include_tax = :i,"
                " total_minor = :t WHERE id = :o"
            ),
            {"s": shipping, "i": included, "t": total, "o": order.id},
        )
        await session.commit()
    async with open_store_session(shop.store_id, world.provider) as session:
        await mark_checkout_paid(
            session,
            order_id=order.id,
            session_id=f"cs_{order.id}",
            payment_intent_id=f"pi_{order.id}",
            amount_minor=total,
            currency="GBP",
        )
        if fulfilled:
            await fulfil_order(session, order.id, "TRK-1")
        await session.commit()
    return order.id


async def _items(world: World, shop: Shop, order_id: str) -> dict[str, str]:  # noqa: F811
    """order item id by variant id."""
    async with open_store_session(shop.store_id, world.provider) as session:
        rows = await session.execute(
            text("SELECT variant_id, id FROM order_items WHERE order_id = :o"),
            {"o": order_id},
        )
        return {row[0]: row[1] for row in rows}


async def _stock(world: World, shop: Shop, variant_id: str) -> int:  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        value = await session.scalar(
            text("SELECT stock FROM variants WHERE id = :v"), {"v": variant_id}
        )
    assert isinstance(value, int)
    return value


async def _status(world: World, shop: Shop, order_id: str) -> str:  # noqa: F811
    async with open_store_session(shop.store_id, world.provider) as session:
        value = await session.scalar(
            text("SELECT status FROM orders WHERE id = :o"), {"o": order_id}
        )
    assert isinstance(value, str)
    return value


async def _reserve(
    world: World,  # noqa: F811
    shop: Shop,
    order_id: str,
    lines: Sequence[RefundLineInput] | None = None,
    *,
    restock: bool = False,
) -> RefundPlan:
    async with open_store_session(shop.store_id, world.provider) as session:
        plan = await reserve_refund(session, order_id, lines, restock=restock)
        await session.commit()
    return plan


async def _settle(
    world: World,  # noqa: F811
    shop: Shop,
    refund_id: str,
    outcome: RefundOutcome = RefundOutcome.SUCCEEDED,
) -> bool:
    async with open_store_session(shop.store_id, world.provider) as session:
        settled = await settle_refund(session, refund_id, outcome)
        await session.commit()
    return settled


# --- stock_taken (take_paid_stock bookkeeping) ------------------------------------------


async def test_paying_an_order_records_the_stock_it_took(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3), (shop.scarce, 2)])

    async with open_store_session(shop.store_id, world.provider) as session:
        rows = await session.execute(
            text("SELECT variant_id, stock_taken FROM order_items WHERE order_id = :o"),
            {"o": order_id},
        )
        taken = {row[0]: row[1] for row in rows}

    assert taken[shop.a] == 3  # covered
    assert taken[shop.scarce] == 0  # stock was 1 for 2 units: not taken, oversold


# --- full refund ------------------------------------------------------------------------


async def test_a_full_refund_without_restock_leaves_stock_alone(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    assert await _stock(world, shop, shop.a) == 7

    plan = await _reserve(world, shop, order_id)
    assert await _settle(world, shop, plan.id) is True

    assert await _stock(world, shop, shop.a) == 7
    assert await _status(world, shop, order_id) == "refunded"


async def test_a_full_refund_amount_is_the_order_total(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3), (shop.b, 1)])

    plan = await _reserve(world, shop, order_id)

    assert plan.amount_minor == 4 * PRICE + 4 * PRICE * TAX_BPS // 10_000
    assert plan.currency == "GBP"
    assert plan.payment_intent_id == f"pi_{order_id}"
    assert plan.restock is False


async def test_restock_returns_the_refunded_quantities_to_stock(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3), (shop.b, 2)])
    assert await _stock(world, shop, shop.a) == 7
    assert await _stock(world, shop, shop.b) == 8

    plan = await _reserve(world, shop, order_id, restock=True)
    await _settle(world, shop, plan.id)

    assert await _stock(world, shop, shop.a) == 10
    assert await _stock(world, shop, shop.b) == 10


async def test_stock_is_not_returned_before_the_refund_succeeds(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])

    plan = await _reserve(world, shop, order_id, restock=True)

    assert await _stock(world, shop, shop.a) == 7
    assert await _status(world, shop, order_id) == "paid"
    await _settle(world, shop, plan.id, RefundOutcome.FAILED)
    assert await _stock(world, shop, shop.a) == 7


# --- idempotency ------------------------------------------------------------------------


async def test_a_replayed_settlement_restocks_once(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    plan = await _reserve(world, shop, order_id, restock=True)

    first = await _settle(world, shop, plan.id)
    second = await _settle(world, shop, plan.id)

    assert (first, second) == (True, False)
    assert await _stock(world, shop, shop.a) == 10


async def test_concurrent_settlements_restock_once(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    plan = await _reserve(world, shop, order_id, restock=True)

    results = await asyncio.gather(*(_settle(world, shop, plan.id) for _ in range(8)))

    assert results.count(True) == 1
    assert await _stock(world, shop, shop.a) == 10


async def test_a_failure_after_a_success_changes_nothing(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    plan = await _reserve(world, shop, order_id, restock=True)
    await _settle(world, shop, plan.id)

    late = await _settle(world, shop, plan.id, RefundOutcome.FAILED)

    assert late is False
    assert await _stock(world, shop, shop.a) == 10
    assert await _status(world, shop, order_id) == "refunded"


async def test_concurrent_identical_reservations_allow_exactly_one(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])

    async def attempt() -> bool:
        try:
            await _reserve(world, shop, order_id)
        except RefundNotAllowed:
            return False
        return True

    results = await asyncio.gather(*(attempt() for _ in range(6)))

    assert results.count(True) == 1


# --- partial refunds --------------------------------------------------------------------


async def test_a_partial_refund_restocks_only_the_refunded_quantities(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3), (shop.b, 2)])
    items = await _items(world, shop, order_id)

    plan = await _reserve(
        world, shop, order_id, [RefundLineInput(items[shop.a], 2)], restock=True
    )
    await _settle(world, shop, plan.id)

    assert await _stock(world, shop, shop.a) == 9  # 7 + 2 of 3
    assert await _stock(world, shop, shop.b) == 8  # untouched
    assert await _status(world, shop, order_id) == "paid"  # not fully refunded


async def test_partial_refunds_add_up_to_the_order_total_and_then_refund_it(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    items = await _items(world, shop, order_id)
    total = 3 * PRICE + 3 * PRICE * TAX_BPS // 10_000

    amounts = []
    for _ in range(3):
        plan = await _reserve(
            world, shop, order_id, [RefundLineInput(items[shop.a], 1)], restock=True
        )
        amounts.append(plan.amount_minor)
        await _settle(world, shop, plan.id)

    assert sum(amounts) == total
    assert await _stock(world, shop, shop.a) == 10  # never above what was taken
    assert await _status(world, shop, order_id) == "refunded"


async def test_a_refund_cannot_exceed_what_remains(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    items = await _items(world, shop, order_id)
    await _reserve(world, shop, order_id, [RefundLineInput(items[shop.a], 2)])

    with pytest.raises(RefundNotAllowed):
        await _reserve(world, shop, order_id, [RefundLineInput(items[shop.a], 2)])


async def test_a_failed_refund_releases_what_it_held(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    first = await _reserve(world, shop, order_id)
    with pytest.raises(RefundNotAllowed):  # the pending refund holds everything
        await _reserve(world, shop, order_id)
    await _settle(world, shop, first.id, RefundOutcome.FAILED)

    again = await _reserve(world, shop, order_id)

    assert again.amount_minor == first.amount_minor


# --- oversold and deleted variants ------------------------------------------------------


async def test_an_oversold_line_is_never_restocked(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    # scarce has 1 unit and the order wants 2: not taken. a (3 units) is taken.
    order_id = await _paid_order(world, shop, [(shop.a, 3), (shop.scarce, 2)])
    assert await _stock(world, shop, shop.scarce) == 1

    plan = await _reserve(world, shop, order_id, restock=True)
    await _settle(world, shop, plan.id)

    assert await _stock(world, shop, shop.a) == 10
    assert (
        await _stock(world, shop, shop.scarce) == 1
    )  # nothing was taken, nothing back


async def test_a_deleted_variant_is_skipped(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3), (shop.b, 2)])
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(text("DELETE FROM variants WHERE id = :v"), {"v": shop.b})
        await session.commit()

    plan = await _reserve(world, shop, order_id, restock=True)
    settled = await _settle(world, shop, plan.id)

    assert settled is True
    assert await _stock(world, shop, shop.a) == 10
    assert await _status(world, shop, order_id) == "refunded"


async def test_stock_added_by_hand_is_kept(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    async with open_store_session(shop.store_id, world.provider) as session:
        await session.execute(
            text("UPDATE variants SET stock = 50 WHERE id = :v"), {"v": shop.a}
        )
        await session.commit()

    plan = await _reserve(world, shop, order_id, restock=True)
    await _settle(world, shop, plan.id)

    assert await _stock(world, shop, shop.a) == 53  # its own 3 units, no more


# --- refusals ---------------------------------------------------------------------------


async def test_only_paid_or_fulfilled_orders_can_be_refunded(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    async with open_store_session(shop.store_id, world.provider) as session:
        pending = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=shop.a, quantity=1)],
        )
        await session.commit()

    with pytest.raises(RefundNotAllowed):
        await _reserve(world, shop, pending.id)


async def test_an_order_without_a_payment_cannot_be_refunded(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    async with open_store_session(shop.store_id, world.provider) as session:
        order = await create_order(
            session,
            currency="GBP",
            tax_rate_bps=0,
            lines=[OrderLineInput(variant_id=shop.a, quantity=1)],
        )
        await transition_order(session, order.id, OrderStatus.PAID)  # no payment intent
        await session.commit()

    with pytest.raises(RefundNotAllowed):
        await _reserve(world, shop, order.id)


async def test_an_unknown_order_is_not_found(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    with pytest.raises(OrderNotFound):
        await _reserve(world, shop, new_id())


@pytest.mark.parametrize("quantity", [0, -1, 4, True])
async def test_line_quantities_are_validated(
    world: World,  # noqa: F811
    shop: Shop,
    quantity: int,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    items = await _items(world, shop, order_id)

    with pytest.raises((InvalidOrder, RefundNotAllowed)):
        await _reserve(
            world, shop, order_id, [RefundLineInput(items[shop.a], quantity)]
        )


async def test_a_line_of_another_order_is_refused(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    mine = await _paid_order(world, shop, [(shop.a, 1)])
    other = await _paid_order(world, shop, [(shop.b, 1)])
    other_items = await _items(world, shop, other)

    with pytest.raises(InvalidOrder):
        await _reserve(world, shop, mine, [RefundLineInput(other_items[shop.b], 1)])


async def test_duplicate_or_empty_line_lists_are_refused(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    items = await _items(world, shop, order_id)
    line = RefundLineInput(items[shop.a], 1)

    with pytest.raises(InvalidOrder):
        await _reserve(world, shop, order_id, [line, line])
    with pytest.raises(InvalidOrder):
        await _reserve(world, shop, order_id, [])


# --- amounts: rounding, inclusive prices, shipping ------------------------------------------


async def test_partial_amounts_add_up_to_the_total_when_tax_does_not_divide(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    # 3 x 1000 at 13.33%: tax 400, which three equal parts cannot split.
    order_id = await _paid_order(world, shop, [(shop.a, 3)], tax_bps=1333)
    items = await _items(world, shop, order_id)

    amounts = []
    for _ in range(3):
        plan = await _reserve(
            world, shop, order_id, [RefundLineInput(items[shop.a], 1)]
        )
        amounts.append(plan.amount_minor)
        await _settle(world, shop, plan.id)

    assert amounts == [1133, 1133, 1134]
    assert await _status(world, shop, order_id) == "refunded"


async def test_two_then_one_also_adds_up(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)], tax_bps=1333)
    items = await _items(world, shop, order_id)

    first = await _reserve(world, shop, order_id, [RefundLineInput(items[shop.a], 2)])
    await _settle(world, shop, first.id)
    second = await _reserve(world, shop, order_id, [RefundLineInput(items[shop.a], 1)])

    assert first.amount_minor == 2266
    assert first.amount_minor + second.amount_minor == 3400


async def test_prices_that_include_tax_are_not_taxed_again(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)], included=True)
    items = await _items(world, shop, order_id)

    part = await _reserve(world, shop, order_id, [RefundLineInput(items[shop.a], 2)])
    await _settle(world, shop, part.id)
    rest = await _reserve(world, shop, order_id)

    assert part.amount_minor == 2 * PRICE
    assert rest.amount_minor == PRICE
    await _settle(world, shop, rest.id)
    assert await _status(world, shop, order_id) == "refunded"


async def test_shipping_is_refunded_only_by_a_full_refund(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 2)], shipping=499)
    items = await _items(world, shop, order_id)
    lines_total = 2 * PRICE + 2 * PRICE * TAX_BPS // 10_000

    everything = await _reserve(
        world, shop, order_id, [RefundLineInput(items[shop.a], 2)]
    )
    await _settle(world, shop, everything.id)
    assert everything.amount_minor == lines_total
    assert await _status(world, shop, order_id) == "paid"  # shipping is left

    shipping_only = await _reserve(world, shop, order_id)
    assert shipping_only.amount_minor == 499
    await _settle(world, shop, shipping_only.id)
    assert await _status(world, shop, order_id) == "refunded"


async def test_a_full_refund_includes_shipping(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 2)], shipping=499)

    plan = await _reserve(world, shop, order_id)

    assert plan.amount_minor == 2 * PRICE + 2 * PRICE * TAX_BPS // 10_000 + 499


# --- restock bounds ---------------------------------------------------------------------


async def test_a_line_that_was_not_taken_restocks_nothing(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    # scarce has 1 unit and the line wants 2: it is not taken (all or nothing per line).
    order_id = await _paid_order(world, shop, [(shop.scarce, 2)])

    plan = await _reserve(world, shop, order_id, restock=True)
    await _settle(world, shop, plan.id)

    assert await _stock(world, shop, shop.scarce) == 1
    async with open_store_session(shop.store_id, world.provider) as session:
        restocked = await session.scalar(
            text("SELECT restocked_quantity FROM order_items WHERE order_id = :o"),
            {"o": order_id},
        )
    assert restocked == 0


async def test_only_the_refund_that_asks_for_it_restocks(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 3)])
    items = await _items(world, shop, order_id)

    first = await _reserve(world, shop, order_id, [RefundLineInput(items[shop.a], 1)])
    await _settle(world, shop, first.id)
    second = await _reserve(
        world, shop, order_id, [RefundLineInput(items[shop.a], 2)], restock=True
    )
    await _settle(world, shop, second.id)

    assert await _stock(world, shop, shop.a) == 9  # 7 + the 2 of the restocking refund


# --- order status -----------------------------------------------------------------------


async def test_a_fulfilled_order_can_be_refunded(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 1)], fulfilled=True)

    plan = await _reserve(world, shop, order_id)
    await _settle(world, shop, plan.id)

    assert await _status(world, shop, order_id) == "refunded"


async def test_a_refunded_order_cannot_be_refunded_again(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    order_id = await _paid_order(world, shop, [(shop.a, 1)])
    plan = await _reserve(world, shop, order_id)
    await _settle(world, shop, plan.id)

    with pytest.raises(RefundNotAllowed):
        await _reserve(world, shop, order_id)


async def test_restocked_at_is_set_only_when_something_was_returned(
    world: World,  # noqa: F811
    shop: Shop,
) -> None:
    taken = await _paid_order(world, shop, [(shop.a, 1)])
    untaken = await _paid_order(world, shop, [(shop.scarce, 2)])  # not taken: oversold

    for order_id in (taken, untaken):
        plan = await _reserve(world, shop, order_id, restock=True)
        await _settle(world, shop, plan.id)

    async with open_store_session(shop.store_id, world.provider) as session:
        rows = await session.execute(
            text(
                "SELECT order_id, restocked_at IS NOT NULL FROM order_refunds"
                " WHERE order_id IN (:a, :b)"
            ),
            {"a": taken, "b": untaken},
        )
        flags = {row[0]: row[1] for row in rows}
    assert flags == {taken: True, untaken: False}
