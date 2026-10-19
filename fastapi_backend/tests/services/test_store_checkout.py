"""Checkout on the merchant's connected account without a database (KAN-68).

The platform reads, the store database and Stripe are in-memory fakes; the SQL is covered by
``tests/api/test_checkout_e2e.py``.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import pytest

from app.core.stripe_billing import (
    StripeConflict,
    StripeError,
    StripeNotProcessed,
    StripeRejected,
)
from app.core.stripe_checkout import CheckoutSessionRequest, StripeCheckoutSession
from app.repositories.connect_events import ConnectRoute
from app.repositories.org_connect import ConnectRecord
from app.services import store_checkout
from app.services.store_cart import CartLine, CartView, LineStatus
from app.services.store_checkout import (
    CartNotReady,
    CheckoutStoreNotFound,
    CheckoutTarget,
    CheckoutUnavailable,
    InvalidCheckoutUrl,
    PaymentsNotEnabled,
    PlatformCheckoutTargets,
    SqlCheckoutOrders,
    StoreCheckoutService,
    build_session_request,
    checkout_payment_handler,
    checkout_return_origins,
    confirm_checkout_payment,
    normalize_root_domain,
    platform_fee_minor,
)
from app.services.store_orders import (
    InvalidOrder,
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
ROOT_DOMAIN = (
    "example.com"  # stores live at {slug}.example.com, the app at app.example.com
)
SUCCESS = "https://north.example.com/checkout/success"
CANCEL = "https://north.example.com/cart"
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
        self.create_error: Exception | None = None

    async def view_cart(self, token: str | None) -> CartView:
        return self.view

    async def create_order(
        self, lines: Sequence[OrderLineInput], currency: str
    ) -> OrderRecord:
        self.created.append((tuple(lines), currency))
        if self.create_error is not None:
            raise self.create_error
        return self.priced

    async def attach_session(self, order_id: str, session_id: str) -> None:
        self.attached.append((order_id, session_id))

    async def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)


class FakeStripeCheckout:
    def __init__(self) -> None:
        self.requests: list[CheckoutSessionRequest] = []
        self.errors: list[StripeError] = []  # raised in order, one per call

    async def create_payment_session(
        self, request: CheckoutSessionRequest
    ) -> StripeCheckoutSession:
        self.requests.append(request)
        if self.errors:
            raise self.errors.pop(0)
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
        ROOT_DOMAIN,
        conflict_delay=0,
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


def test_store_return_origin_is_under_the_platform_root_domain() -> None:
    origins = checkout_return_origins(
        frozenset({"https://app.storecart.com"}), "shop", "storecart.com"
    )

    assert origins == {"https://app.storecart.com", "https://shop.storecart.com"}


def test_store_return_origin_keeps_the_scheme_and_port_of_a_local_app_origin() -> None:
    origins = checkout_return_origins(
        frozenset({"http://localhost:3000", "https://elsewhere.test"}),
        "north",
        "localhost",
    )

    assert origins == {
        "http://localhost:3000",
        "https://elsewhere.test",
        "https://north.localhost",
        "http://north.localhost:3000",
    }


@pytest.mark.parametrize(
    "root", [None, "", "https://storecart.com", "storecart.com/x", "bad host"]
)
def test_without_a_valid_root_domain_only_app_origins_are_allowed(
    root: str | None,
) -> None:
    origins = checkout_return_origins(
        frozenset({"https://app.storecart.com"}), "shop", root
    )

    assert origins == {"https://app.storecart.com"}


def test_root_domain_is_normalised() -> None:
    assert normalize_root_domain(" StoreCart.COM. ") == "storecart.com"


async def test_a_return_url_on_another_stores_subdomain_is_refused() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()

    with pytest.raises(InvalidCheckoutUrl):
        await service(orders, stripe).start(
            SLUG, "token", "https://south.example.com/ok", CANCEL
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


async def test_a_stripe_refusal_cancels_the_unstarted_order() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()
    stripe.errors = [StripeRejected("Stripe request failed")]

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert orders.cancelled == ["order1"]
    assert orders.attached == []
    assert len(stripe.requests) == 1


async def test_an_unknown_outcome_is_retried_with_the_same_key() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()
    stripe.errors = [StripeError("timeout")]

    started = await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert started.order_id == "order1"
    assert [r.idempotency_key for r in stripe.requests] == [
        f"sc-checkout-{STORE_ID}-order1"
    ] * 2
    assert orders.cancelled == []
    assert orders.attached == [("order1", "cs_test_1")]


@pytest.mark.parametrize("error", [StripeError("timeout"), StripeConflict("in flight")])
async def test_an_outcome_that_stays_unknown_leaves_the_order_pending(
    error: StripeError,
) -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()
    stripe.errors = [error, error]

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert len(stripe.requests) == 2
    assert orders.cancelled == []
    assert orders.attached == []


# --- store adapter, platform lookup and webhook side, without a database -----------------


class BrokenSession:
    """An AsyncSession whose statements fail; records rollbacks."""

    def __init__(self) -> None:
        self.rollbacks = 0

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("connection lost")

    async def commit(self) -> None:
        raise AssertionError("nothing to commit")

    async def rollback(self) -> None:
        self.rollbacks += 1


def sql_orders(session: BrokenSession) -> SqlCheckoutOrders:
    return SqlCheckoutOrders(session, None, None)  # type: ignore[arg-type]


async def test_a_failed_cancel_is_logged_and_rolled_back_not_raised() -> None:
    session = BrokenSession()

    await sql_orders(session).cancel_order("order1")

    assert session.rollbacks == 1


async def test_a_failed_session_link_does_not_lose_the_checkout_url() -> None:
    session = BrokenSession()

    await sql_orders(session).attach_session("order1", "cs_test_1")

    assert session.rollbacks == 1


class NoProvider:
    def session(self) -> Any:
        raise AssertionError("an invalid slug must not reach the database")


@pytest.mark.parametrize("slug", ["Not A Slug!", "admin", ""])
async def test_an_invalid_or_reserved_slug_finds_no_store(slug: str) -> None:
    targets = PlatformCheckoutTargets(NoProvider())  # type: ignore[arg-type]

    assert await targets.find(slug) is None


def paid_object(**changes: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": "cs_test_1",
        "payment_status": "paid",
        "amount_total": 2000,
        "currency": "gbp",
        "payment_intent": "pi_1",
        "metadata": {"store_id": STORE_ID, "order_id": "order1"},
    }
    obj.update(changes)
    return obj


@pytest.mark.parametrize(
    "obj",
    [
        paid_object(payment_status="unpaid"),
        paid_object(metadata=None),
        paid_object(metadata={"store_id": STORE_ID}),
        paid_object(metadata={"order_id": "bad id!"}),
        paid_object(id="pi_not_a_session"),
        paid_object(amount_total=0),
        paid_object(amount_total=True),
        paid_object(amount_total="2000"),
        paid_object(currency="GBP"),
        paid_object(currency=None),
    ],
)
async def test_an_unpaid_or_unusable_session_writes_nothing(
    obj: dict[str, Any],
) -> None:
    session = BrokenSession()  # any statement would raise

    outcome = await confirm_checkout_payment(session, obj)  # type: ignore[arg-type]

    assert outcome is None


@pytest.mark.parametrize("bps", [-1, 10_001])
async def test_an_out_of_range_fee_rate_is_refused_before_anything_is_written(
    bps: int,
) -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe, target(platform_fee_bps=bps)).start(
            SLUG, "token", SUCCESS, CANCEL
        )

    assert orders.created == []
    assert stripe.requests == []


async def test_a_request_that_cannot_be_built_cancels_the_written_order() -> None:
    broken = replace(order(item("mug", 1000, 2)), total_minor=1)
    orders = ready_orders(broken)
    stripe = FakeStripeCheckout()

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert orders.cancelled == ["order1"]
    assert stripe.requests == []


async def test_a_catalogue_change_after_the_cart_view_is_a_changed_cart() -> None:
    orders = ready_orders()
    orders.create_error = InvalidOrder("An item is not available")
    stripe = FakeStripeCheckout()

    with pytest.raises(CartNotReady):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert stripe.requests == []


@pytest.mark.parametrize("status_error", ["401", "429"])
async def test_a_request_stripe_did_not_process_cancels_the_order(
    status_error: str,
) -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()
    stripe.errors = [StripeNotProcessed(status_error)]

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert orders.cancelled == ["order1"]
    assert len(stripe.requests) == 1


async def test_a_conflict_then_success_uses_the_session_stripe_returns() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()
    stripe.errors = [StripeConflict("in flight")]

    started = await service(orders, stripe).start(SLUG, "token", SUCCESS, CANCEL)

    assert started.checkout_url.endswith("cs_test_1")
    assert len(stripe.requests) == 2
    assert orders.cancelled == []


async def test_a_storeless_payment_event_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(store_checkout, "report_exception", reported.append)
    handler = checkout_payment_handler(lambda store_id: None)  # type: ignore[arg-type,return-value]

    await handler(ConnectRoute("org1", ACCOUNT, None), paid_object())

    assert [str(error) for error in reported] == ["no store"]
