"""Checkout on the merchant's connected account without a database (KAN-68).

The platform reads, the store database and Stripe are in-memory fakes; the SQL is covered by
``tests/api/test_checkout_e2e.py``.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import pytest

from app.core.stripe_billing import StripeError
from app.core.stripe_checkout import CheckoutSessionRequest, StripeCheckoutSession
from app.repositories.org_connect import ConnectRecord
from app.services.store_cart import CartLine, CartView, LineStatus
from app.services.store_checkout import (
    CartNotReady,
    CheckoutStoreNotFound,
    CheckoutTarget,
    CheckoutUnavailable,
    InvalidCheckoutUrl,
    PaymentsNotEnabled,
    StoreCheckoutService,
    build_session_request,
    checkout_return_origins,
    platform_fee_minor,
)
from app.services.store_orders import (
    OrderItemRecord,
    OrderLineInput,
    OrderRecord,
    OrderStatus,
)
from app.services.store_totals import Totals

ACCOUNT = "acct_merchant1"
STORE_ID = "store1"
SLUG = "north"
ORIGINS = frozenset({"https://app.example.com"})
SUCCESS = "https://north.app.example.com/checkout/success"
CANCEL = "https://north.app.example.com/cart"
CONNECTED = ConnectRecord(
    id="org1",
    stripe_connect_account_id=ACCOUNT,
    connect_charges_enabled=True,
    connect_payouts_enabled=True,
    connect_details_submitted=True,
)


def target(**changes: Any) -> CheckoutTarget:
    base = CheckoutTarget(
        store_id=STORE_ID,
        slug=SLUG,
        connect=CONNECTED,
        platform_fee_bps=0,
        currency="GBP",
    )
    return replace(base, **changes)


def item(name: str, price: int, quantity: int, tax: int = 0) -> OrderItemRecord:
    return OrderItemRecord(
        id=f"item-{name}",
        product_id="p1",
        variant_id=f"v-{name}",
        product_name=name,
        sku=f"SKU-{name}",
        variant_label=None,
        unit_price_minor=price,
        quantity=quantity,
        tax_rate_bps=2000 if tax else 0,
        tax_minor=tax,
    )


def order(
    *items: OrderItemRecord, shipping: int = 0, included: bool = False
) -> OrderRecord:
    subtotal = sum(i.unit_price_minor * i.quantity for i in items)
    tax = sum(i.tax_minor for i in items)
    return OrderRecord(
        id="order1",
        status=OrderStatus.PENDING,
        currency="GBP",
        subtotal_minor=subtotal,
        tax_minor=tax,
        total_minor=subtotal + shipping + (0 if included else tax),
        items=tuple(items),
        shipping_minor=shipping,
        prices_include_tax=included,
    )


def cart_line(variant_id: str, price: int, quantity: int) -> CartLine:
    return CartLine(
        variant_id=variant_id,
        product_id="p1",
        product_name="Mug",
        product_slug="mug",
        sku="SKU",
        variant_label=None,
        unit_price_minor=price,
        quantity=quantity,
        line_total_minor=price * quantity,
        available_stock=10,
        status=LineStatus.OK,
    )


def cart(*lines: CartLine, can_checkout: bool = True) -> CartView:
    subtotal = sum(line.line_total_minor for line in lines)
    return CartView(
        lines=tuple(lines),
        totals=Totals(subtotal, 0, 0, subtotal, False),
        can_checkout=can_checkout,
    )


class FakeTargets:
    def __init__(self, found: CheckoutTarget | None) -> None:
        self.found = found

    async def find(self, slug: str) -> CheckoutTarget | None:
        return self.found


class FakeOrders:
    """The store database: a cart, and the orders the service writes."""

    def __init__(self, view: CartView, priced: OrderRecord) -> None:
        self.view = view
        self.priced = priced
        self.created: list[tuple[tuple[OrderLineInput, ...], str]] = []
        self.attached: list[tuple[str, str]] = []
        self.cancelled: list[str] = []

    async def view_cart(self, token: str | None) -> CartView:
        return self.view

    async def create_order(
        self, lines: Sequence[OrderLineInput], currency: str
    ) -> OrderRecord:
        self.created.append((tuple(lines), currency))
        return self.priced

    async def attach_session(self, order_id: str, session_id: str) -> None:
        self.attached.append((order_id, session_id))

    async def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)


class FakeStripeCheckout:
    def __init__(self) -> None:
        self.requests: list[CheckoutSessionRequest] = []
        self.fail = False

    async def create_payment_session(
        self, request: CheckoutSessionRequest
    ) -> StripeCheckoutSession:
        self.requests.append(request)
        if self.fail:
            raise StripeError("Stripe request failed")
        return StripeCheckoutSession(
            id="cs_test_1", url="https://checkout.stripe.com/c/pay/cs_test_1"
        )


def service(
    orders: FakeOrders,
    stripe: FakeStripeCheckout,
    found: CheckoutTarget | None = None,
) -> StoreCheckoutService:
    @asynccontextmanager
    async def open_orders(store_id: str) -> AsyncIterator[FakeOrders]:
        assert store_id == STORE_ID
        yield orders

    return StoreCheckoutService(
        FakeTargets(found if found is not None else target()),
        open_orders,
        stripe,
        ORIGINS,
    )


def ready_orders(priced: OrderRecord | None = None) -> FakeOrders:
    return FakeOrders(
        cart(cart_line("v-mug", 1000, 2)), priced or order(item("mug", 1000, 2))
    )


# --- platform fee -----------------------------------------------------------------------


def test_fee_is_zero_when_the_rate_is_zero() -> None:
    assert platform_fee_minor(10_000, 0) == 0


def test_fee_rounds_half_up_in_minor_units() -> None:
    assert platform_fee_minor(1_250, 100) == 13  # 12.5 -> 13
    assert platform_fee_minor(1_249, 100) == 12  # 12.49 -> 12
    assert platform_fee_minor(999, 250) == 25  # 24.975 -> 25


@pytest.mark.parametrize("bps", [-1, 10_001, True])
def test_fee_rate_outside_zero_to_ten_thousand_is_refused(bps: int) -> None:
    with pytest.raises(ValueError):
        platform_fee_minor(1_000, bps)


def test_zero_fee_is_left_out_of_the_session_request() -> None:
    request = build_session_request(
        target(platform_fee_bps=0), order(item("mug", 1000, 2)), SUCCESS, CANCEL
    )

    assert request.application_fee_minor is None


def test_positive_fee_is_computed_from_the_order_total() -> None:
    request = build_session_request(
        target(platform_fee_bps=150),
        order(item("mug", 1000, 2), shipping=499),
        SUCCESS,
        CANCEL,
    )

    assert request.application_fee_minor == 37  # 2499 * 1.5% = 37.485 -> 37


def test_a_fee_that_rounds_to_zero_is_left_out() -> None:
    request = build_session_request(
        target(platform_fee_bps=1), order(item("pin", 10, 1)), SUCCESS, CANCEL
    )

    assert request.application_fee_minor is None


# --- session request: direct charge with server amounts ---------------------------------


def test_request_is_a_direct_charge_on_the_connected_account() -> None:
    request = build_session_request(
        target(), order(item("mug", 1000, 2)), SUCCESS, CANCEL
    )

    assert request.account_id == ACCOUNT
    assert request.store_id == STORE_ID
    assert request.order_id == "order1"
    assert request.currency == "gbp"
    assert request.idempotency_key == f"sc-checkout-{STORE_ID}-order1"
    assert (request.success_url, request.cancel_url) == (SUCCESS, CANCEL)


def test_line_items_add_up_to_the_order_total_with_tax_and_shipping() -> None:
    priced = order(
        item("mug", 1000, 2, tax=400), item("cap", 550, 1, tax=110), shipping=499
    )

    request = build_session_request(target(), priced, SUCCESS, CANCEL)

    amounts = [
        (li.name, li.unit_amount_minor, li.quantity) for li in request.line_items
    ]
    assert amounts == [
        ("mug", 1000, 2),
        ("cap", 550, 1),
        ("Tax", 510, 1),
        ("Shipping", 499, 1),
    ]
    assert sum(li.unit_amount_minor * li.quantity for li in request.line_items) == (
        priced.total_minor
    )


def test_included_tax_is_not_charged_again() -> None:
    priced = order(item("mug", 1200, 1, tax=200), included=True)

    request = build_session_request(target(), priced, SUCCESS, CANCEL)

    assert [li.name for li in request.line_items] == ["mug"]
    assert request.line_items[0].unit_amount_minor == priced.total_minor == 1200


def test_variant_label_is_part_of_the_line_name() -> None:
    labelled = replace(item("mug", 1000, 1), variant_label="Large / Red")

    request = build_session_request(target(), order(labelled), SUCCESS, CANCEL)

    assert request.line_items[0].name == "mug (Large / Red)"


def test_a_request_that_does_not_add_up_is_refused() -> None:
    broken = replace(order(item("mug", 1000, 1)), total_minor=1)

    with pytest.raises(ValueError):
        build_session_request(target(), broken, SUCCESS, CANCEL)


# --- return URLs ------------------------------------------------------------------------


def test_return_urls_may_use_the_store_subdomain_or_an_allowed_origin() -> None:
    origins = checkout_return_origins(
        frozenset({"https://www.example.com", "http://localhost:3000"}), "north"
    )

    assert origins == {
        "https://www.example.com",
        "https://north.example.com",
        "http://localhost:3000",
        "http://north.localhost:3000",
    }


async def test_a_return_url_on_another_stores_subdomain_is_refused() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()

    with pytest.raises(InvalidCheckoutUrl):
        await service(orders, stripe).start(
            SLUG, "token", "https://south.app.example.com/ok", CANCEL
        )

    assert orders.created == []
    assert stripe.requests == []


# --- the service ------------------------------------------------------------------------


async def test_start_creates_the_order_then_the_session_and_links_them() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()

    started = await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert started.order_id == "order1"
    assert started.checkout_url == "https://checkout.stripe.com/c/pay/cs_test_1"
    assert orders.created == [((OrderLineInput("v-mug", 2),), "GBP")]
    assert orders.attached == [("order1", "cs_test_1")]
    assert stripe.requests[0].account_id == ACCOUNT


async def test_amounts_come_from_the_server_priced_order_not_the_cart() -> None:
    # The cart said 1000 a unit; the order (priced from the catalogue under lock) says 1200.
    orders = ready_orders(order(item("mug", 1200, 2), shipping=300))
    stripe = FakeStripeCheckout()

    await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    request = stripe.requests[0]
    assert [li.unit_amount_minor for li in request.line_items] == [1200, 300]
    assert orders.created[0][0] == (OrderLineInput("v-mug", 2),)


@pytest.mark.parametrize(
    "connect",
    [
        replace(CONNECTED, connect_charges_enabled=False),
        replace(CONNECTED, stripe_connect_account_id=None),
    ],
)
async def test_checkout_is_refused_until_charges_are_enabled(
    connect: ConnectRecord,
) -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()

    with pytest.raises(PaymentsNotEnabled):
        await service(orders, stripe, target(connect=connect)).start(
            SLUG, "token", SUCCESS, CANCEL
        )

    assert orders.created == []
    assert stripe.requests == []


async def test_unknown_store_is_not_found() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()
    svc = service(orders, stripe)
    svc._targets = FakeTargets(None)  # type: ignore[assignment]

    with pytest.raises(CheckoutStoreNotFound):
        await svc.start(SLUG, "token", SUCCESS, CANCEL)

    assert stripe.requests == []


@pytest.mark.parametrize(
    "view",
    [cart(), cart(cart_line("v-mug", 1000, 1), can_checkout=False)],
)
async def test_an_empty_or_changed_cart_is_refused(view: CartView) -> None:
    orders = FakeOrders(view, order(item("mug", 1000, 1)))
    stripe = FakeStripeCheckout()

    with pytest.raises(CartNotReady):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert orders.created == []
    assert stripe.requests == []


async def test_a_zero_total_is_refused_and_the_order_cancelled() -> None:
    orders = ready_orders(order(item("free", 0, 1)))
    stripe = FakeStripeCheckout()

    with pytest.raises(CartNotReady):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert orders.cancelled == ["order1"]
    assert stripe.requests == []


async def test_a_stripe_failure_cancels_the_unstarted_order() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()
    stripe.fail = True

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert orders.cancelled == ["order1"]
    assert orders.attached == []
