"""Order status rule and money arithmetic of the store order service (KAN-78). No database."""

import itertools

import pytest

from app.services.store_orders import (
    ALLOWED_TRANSITIONS,
    InvalidOrder,
    InvalidOrderTransition,
    OrderLineInput,
    OrderStatus,
    can_transition,
    create_order,
    ensure_transition,
    line_tax_minor,
)

ALLOWED = {
    (OrderStatus.PENDING, OrderStatus.PAID),
    (OrderStatus.PENDING, OrderStatus.CANCELLED),
    (OrderStatus.PAID, OrderStatus.FULFILLED),
    (OrderStatus.PAID, OrderStatus.CANCELLED),
    (OrderStatus.PAID, OrderStatus.REFUNDED),
    (OrderStatus.FULFILLED, OrderStatus.REFUNDED),
}
ALL_PAIRS = list(itertools.product(OrderStatus, OrderStatus))


def test_status_values_match_the_database_check():
    assert {status.value for status in OrderStatus} == {
        "pending",
        "paid",
        "fulfilled",
        "cancelled",
        "refunded",
    }


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED))
def test_the_documented_moves_are_allowed(current: OrderStatus, target: OrderStatus):
    assert can_transition(current, target)
    ensure_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"), [pair for pair in ALL_PAIRS if pair not in ALLOWED]
)
def test_every_other_move_is_rejected(current: OrderStatus, target: OrderStatus):
    assert not can_transition(current, target)
    with pytest.raises(InvalidOrderTransition) as caught:
        ensure_transition(current, target)
    assert caught.value.current is current
    assert caught.value.target is target


def test_cancelled_and_refunded_are_terminal():
    assert ALLOWED_TRANSITIONS[OrderStatus.CANCELLED] == frozenset()
    assert ALLOWED_TRANSITIONS[OrderStatus.REFUNDED] == frozenset()


def test_no_move_goes_backwards_in_the_happy_path():
    order = [OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.FULFILLED]
    for later, earlier in itertools.combinations(reversed(order), 2):
        assert not can_transition(later, earlier)


@pytest.mark.parametrize(
    ("unit", "quantity", "rate_bps", "expected"),
    [
        (1000, 2, 2000, 400),  # 20% of 2000
        (999, 1, 2000, 200),  # 199.8 rounds half up to 200
        (1, 1, 5000, 1),  # 0.5 rounds up
        (1, 1, 4999, 0),  # 0.4999 rounds down
        (1000, 3, 0, 0),
        (0, 5, 2000, 0),
    ],
)
def test_line_tax_is_rounded_half_up_in_minor_units(
    unit: int, quantity: int, rate_bps: int, expected: int
):
    assert line_tax_minor(unit, quantity, rate_bps) == expected


class _NoSession:
    """create_order must reject bad input before it touches the session."""

    async def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("the session must not be used")


@pytest.mark.parametrize(
    ("currency", "lines"),
    [
        ("ÉÉÉ", [OrderLineInput("a", 1)]),
        ("GBP", [OrderLineInput("a", 1), OrderLineInput("a", 2)]),
        ("GBP", [OrderLineInput(str(i), 1) for i in range(101)]),
        ("GBP", []),
        ("GBP", [OrderLineInput("a", 0)]),
    ],
)
async def test_create_order_rejects_bad_input_before_using_the_session(
    currency: str, lines: list[OrderLineInput]
):
    with pytest.raises(InvalidOrder):
        await create_order(
            _NoSession(),  # type: ignore[arg-type]
            currency=currency,
            tax_rate_bps=0,
            lines=lines,
        )


@pytest.mark.parametrize(
    ("quantity", "tax_rate_bps", "variant_id"),
    [
        (True, 0, "a"),  # bool is an int subclass but not a quantity
        (1.0, 0, "a"),
        ("1", 0, "a"),
        (1, True, "a"),
        (1, 20.0, "a"),
        (1, "20", "a"),
        (1, 0, ""),
        (1, 0, "a\0b"),
        (1, 0, "x" * 101),
        (1, 0, None),
        (1, 0, 5),
    ],
)
async def test_create_order_rejects_wrongly_typed_input(
    quantity: object, tax_rate_bps: object, variant_id: object
):
    with pytest.raises(InvalidOrder):
        await create_order(
            _NoSession(),  # type: ignore[arg-type]
            currency="GBP",
            tax_rate_bps=tax_rate_bps,  # type: ignore[arg-type]
            lines=[OrderLineInput(variant_id, quantity)],  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("currency", [None, 826, "GB", "GBPP", "G1P", "gbp", "£££"])
async def test_create_order_rejects_a_bad_currency(currency: object):
    with pytest.raises(InvalidOrder):
        await create_order(
            _NoSession(),  # type: ignore[arg-type]
            currency=currency,  # type: ignore[arg-type]
            tax_rate_bps=0,
            lines=[OrderLineInput("a", 1)],
        )
