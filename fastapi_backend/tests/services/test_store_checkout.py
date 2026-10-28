"""Checkout on the merchant's connected account without a database (KAN-68).

The platform reads, the store database and Stripe are in-memory fakes; the SQL is covered by
``tests/api/test_checkout_e2e.py``.
"""

import itertools
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.stripe_billing import (
    StripeConflict,
    StripeError,
    StripeNotProcessed,
    StripeRejected,
)
from app.core.stripe_checkout import (
    CheckoutSessionRequest,
    ExpireOutcome,
    StripeCheckoutSession,
)
from app.repositories.connect_events import ConnectRoute
from app.repositories.org_connect import ConnectRecord
from app.services import store_checkout
from app.services.order_email_job import EnqueueFailed, OrderEmailJob
from app.services.order_email_templates import OrderEmailKind
from app.services.store_cart import CartLine, CartView, LineStatus
from app.services.store_checkout import (
    CartNotReady,
    CheckoutStoreNotFound,
    CheckoutTarget,
    CheckoutUnavailable,
    InvalidCheckoutUrl,
    OpenOrderExists,
    PaymentInProgress,
    PaymentsNotEnabled,
    PlatformCheckoutTargets,
    SqlCheckoutOrders,
    StoreCheckoutService,
    build_session_request,
    checkout_fingerprint,
    checkout_payment_handler,
    checkout_return_origins,
    confirm_checkout_payment,
    normalize_root_domain,
    platform_fee_minor,
)
from app.services.store_orders import (
    CheckoutOrigin,
    InvalidOrder,
    OpenCheckout,
    OrderItemRecord,
    OrderLineInput,
    OrderRecord,
    OrderStatus,
    PaymentOutcome,
)
from app.services.store_totals import Totals
from tests.fakes_email import RecordingEnqueuer

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
        self.origins: list[CheckoutOrigin] = []
        self.attached: list[tuple[str, str]] = []
        self.urls: list[str] = []
        self.cancelled: list[str] = []
        self.retired: list[str] = []
        self.create_errors: list[Exception] = []  # raised in order, one per call
        self.open_orders: list[
            OpenCheckout | None
        ] = []  # answers of find_open_checkout
        self.cart_id: str | None = "cart1"
        self.sweeps = 0

    async def view_cart(self, token: str | None) -> CartView:
        return self.view

    async def sweep(self) -> None:
        self.sweeps += 1

    async def find_cart(self, token: str | None) -> str | None:
        return self.cart_id

    async def find_open_checkout(self, cart_id: str) -> OpenCheckout | None:
        return self.open_orders.pop(0) if self.open_orders else None

    async def load_order(self, order_id: str) -> OrderRecord:
        return self.priced

    async def create_order(
        self, lines: Sequence[OrderLineInput], currency: str, origin: CheckoutOrigin
    ) -> OrderRecord:
        self.created.append((tuple(lines), currency))
        self.origins.append(origin)
        if self.create_errors:
            raise self.create_errors.pop(0)
        return self.priced

    async def attach_session(self, order_id: str, session_id: str, url: str) -> None:
        self.attached.append((order_id, session_id))
        self.urls.append(url)

    async def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    async def cancel_pending(self, order_id: str) -> bool:
        self.retired.append(order_id)
        return True


class FakeStripeCheckout:
    def __init__(self) -> None:
        self.requests: list[CheckoutSessionRequest] = []
        self.errors: list[StripeError] = []  # raised in order, one per call
        self.expired: list[tuple[str, str]] = []
        self.expire_outcome = ExpireOutcome.EXPIRED
        self.expire_error: StripeError | None = None

    async def expire_session(self, account_id: str, session_id: str) -> ExpireOutcome:
        self.expired.append((account_id, session_id))
        if self.expire_error is not None:
            raise self.expire_error
        return self.expire_outcome

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
    assert amounts == [  # items in a stable order (variant id), then tax, then shipping
        ("cap", 550, 1),
        ("mug", 1000, 2),
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

    await sql_orders(session).attach_session(
        "order1", "cs_test_1", "https://checkout.stripe.com/c/pay/cs_test_1"
    )

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
    orders.create_errors = [InvalidOrder("An item is not available")]
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
    handler = checkout_payment_handler(lambda store_id: None, RecordingEnqueuer())  # type: ignore[arg-type,return-value]

    await handler(ConnectRoute("org1", ACCOUNT, None), paid_object())

    assert [str(error) for error in reported] == ["no store"]


# --- order emails on payment (KAN-81) ------------------------------------------------------


class CommitSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class EmailWrites:
    """Replaces the SQL of the payment handler: the outcome, the outbox rows, the pending read."""

    def __init__(self, outcome: PaymentOutcome, pending: list[str]) -> None:
        self.outcome = outcome
        self.pending = pending
        self.recorded: list[tuple[str, tuple[OrderEmailKind, ...], str | None]] = []
        self.session = CommitSession()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mark_paid(session: Any, **kw: Any) -> PaymentOutcome:
            return self.outcome

        async def record(session: Any, **kw: Any) -> list[OrderEmailKind]:
            assert self.session.commits == 0  # in the payment's transaction
            self.recorded.append(
                (kw["order_id"], tuple(kw["kinds"]), kw["customer_email"])
            )
            return list(kw["kinds"])

        async def pending(session: Any, **kw: Any) -> list[OrderEmailJob]:
            assert self.session.commits == 1  # read after the commit
            return [
                OrderEmailJob(kw["store_id"], kw["order_id"], OrderEmailKind(kind))
                for kind in self.pending
            ]

        monkeypatch.setattr(store_checkout, "mark_checkout_paid", mark_paid)
        monkeypatch.setattr(store_checkout, "report_exception", lambda error: None)
        monkeypatch.setattr(store_checkout, "record_order_emails", record)
        monkeypatch.setattr(store_checkout, "pending_jobs", pending)

    def opener(self) -> Any:
        @asynccontextmanager
        async def open_store(store_id: str) -> AsyncIterator[CommitSession]:
            yield self.session

        return open_store


ROUTE = ConnectRoute("org1", ACCOUNT, STORE_ID)
BOTH = ["new_order_alert", "order_confirmation"]
WITH_EMAIL = paid_object(customer_details={"email": " shopper@example.com "})


async def test_the_paying_delivery_records_and_publishes_both_emails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes = EmailWrites(PaymentOutcome.PAID, BOTH)
    writes.install(monkeypatch)
    enqueuer = RecordingEnqueuer()

    await checkout_payment_handler(writes.opener(), enqueuer)(ROUTE, WITH_EMAIL)

    assert writes.recorded == [
        (
            "order1",
            (OrderEmailKind.ORDER_CONFIRMATION, OrderEmailKind.NEW_ORDER_ALERT),
            "shopper@example.com",
        )
    ]
    assert [(j.store_id, j.order_id, j.kind.value) for j in enqueuer.jobs] == [
        (STORE_ID, "order1", "new_order_alert"),
        (STORE_ID, "order1", "order_confirmation"),
    ]


async def test_a_redelivery_republishes_what_is_still_pending_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes = EmailWrites(PaymentOutcome.ALREADY_PAID, ["order_confirmation"])
    writes.install(monkeypatch)
    enqueuer = RecordingEnqueuer()

    await checkout_payment_handler(writes.opener(), enqueuer)(ROUTE, WITH_EMAIL)

    assert writes.recorded == []
    assert [j.kind.value for j in enqueuer.jobs] == ["order_confirmation"]


@pytest.mark.parametrize(
    ("outcome", "obj"),
    [
        (PaymentOutcome.MISMATCH, WITH_EMAIL),
        (PaymentOutcome.NOT_FOUND, WITH_EMAIL),
        (PaymentOutcome.PAID, paid_object(payment_status="unpaid")),
        (PaymentOutcome.PAID, paid_object(metadata=None)),  # unusable
    ],
)
async def test_a_payment_that_changed_nothing_publishes_nothing(
    outcome: PaymentOutcome, obj: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    writes = EmailWrites(outcome, BOTH)
    writes.install(monkeypatch)
    enqueuer = RecordingEnqueuer()

    await checkout_payment_handler(writes.opener(), enqueuer)(ROUTE, obj)

    assert writes.recorded == []
    assert enqueuer.jobs == []
    assert writes.session.commits == 1


async def test_a_publish_failure_fails_the_delivery_after_the_store_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes = EmailWrites(PaymentOutcome.PAID, BOTH)
    writes.install(monkeypatch)

    with pytest.raises(EnqueueFailed):
        await checkout_payment_handler(writes.opener(), RecordingEnqueuer(fail=True))(
            ROUTE, WITH_EMAIL
        )

    assert writes.session.commits == 1  # the payment itself is kept


def test_the_paid_session_carries_a_clean_customer_email() -> None:
    clean = store_checkout._paid_session(WITH_EMAIL)
    odd = store_checkout._paid_session(paid_object(customer_details={"email": "x"}))
    absent = store_checkout._paid_session(paid_object(customer_details=None))

    assert clean is not None and clean.customer_email == "shopper@example.com"
    assert odd is not None and odd.customer_email is None
    assert absent is not None and absent.customer_email is None


# --- one open order per cart (KAN-256) ----------------------------------------------------

FUTURE = datetime.now(UTC) + timedelta(minutes=20)
RESUMABLE = datetime.now(UTC) + timedelta(minutes=40)  # Stripe still takes this expiry
ENDING = datetime.now(UTC) + timedelta(minutes=2)  # inside the reuse margin
PAST = datetime.now(UTC) - timedelta(minutes=1)


def fingerprint_of(orders: FakeOrders) -> str:
    return checkout_fingerprint(orders.view, "GBP", SUCCESS, CANCEL)


def open_order(
    orders: FakeOrders,
    *,
    fingerprint: str | None = None,
    session_id: str | None = "cs_old",
    url: str | None = "https://checkout.stripe.com/c/pay/cs_old",
    expires_at: datetime | None = FUTURE,
) -> OpenCheckout:
    return OpenCheckout(
        order_id="old1",
        fingerprint=fingerprint if fingerprint is not None else fingerprint_of(orders),
        session_id=session_id,
        url=url,
        expires_at=expires_at,
    )


async def test_the_session_expires_at_the_orders_expiry() -> None:
    orders = ready_orders()
    stripe = FakeStripeCheckout()

    await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    origin = orders.origins[0]
    assert stripe.requests[0].expires_at == int(origin.expires_at.timestamp())
    lifetime = origin.expires_at - datetime.now(UTC)
    assert timedelta(minutes=55) < lifetime <= timedelta(minutes=61)
    assert (origin.cart_id, origin.fingerprint) == ("cart1", fingerprint_of(orders))


async def test_start_sweeps_expired_orders_first() -> None:
    orders = ready_orders()

    await service(orders, FakeStripeCheckout()).start(SLUG, "tok", SUCCESS, CANCEL)

    assert orders.sweeps == 1


async def test_an_unchanged_cart_gets_the_open_sessions_url_and_nothing_new() -> None:
    orders = ready_orders()
    orders.open_orders = [open_order(orders)]
    stripe = FakeStripeCheckout()

    started = await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert started == store_checkout.CheckoutStarted(
        "old1", "https://checkout.stripe.com/c/pay/cs_old"
    )
    assert (orders.created, stripe.requests, stripe.expired) == ([], [], [])


async def test_a_changed_cart_expires_the_old_session_and_cancels_its_order() -> None:
    orders = ready_orders()
    orders.open_orders = [open_order(orders, fingerprint="a-different-cart")]
    stripe = FakeStripeCheckout()

    started = await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert stripe.expired == [(ACCOUNT, "cs_old")]
    assert orders.retired == ["old1"]
    assert started.order_id == "order1"
    assert len(stripe.requests) == 1


async def test_different_return_urls_replace_the_open_order() -> None:
    orders = ready_orders()
    orders.open_orders = [
        open_order(
            orders,
            fingerprint=checkout_fingerprint(
                orders.view, "GBP", SUCCESS, "https://north.example.com/other"
            ),
        )
    ]
    stripe = FakeStripeCheckout()

    await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert orders.retired == ["old1"]
    assert stripe.expired == [(ACCOUNT, "cs_old")]


async def test_an_expired_open_order_is_replaced_even_for_an_unchanged_cart() -> None:
    orders = ready_orders()
    orders.open_orders = [open_order(orders, expires_at=PAST)]
    stripe = FakeStripeCheckout()

    await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert orders.retired == ["old1"]
    assert len(stripe.requests) == 1


async def test_an_old_session_that_was_paid_blocks_a_new_checkout() -> None:
    orders = ready_orders()
    orders.open_orders = [open_order(orders, fingerprint="a-different-cart")]
    stripe = FakeStripeCheckout()
    stripe.expire_outcome = ExpireOutcome.COMPLETE

    with pytest.raises(PaymentInProgress):
        await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert (orders.retired, orders.created, stripe.requests) == ([], [], [])


async def test_an_old_session_that_cannot_be_expired_blocks_a_new_checkout() -> None:
    orders = ready_orders()
    orders.open_orders = [open_order(orders, fingerprint="a-different-cart")]
    stripe = FakeStripeCheckout()
    stripe.expire_error = StripeError("down")

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert (orders.retired, orders.created, stripe.requests) == ([], [], [])


async def test_a_live_unlinked_order_is_not_replaced_while_its_session_may_exist() -> (
    None
):
    orders = ready_orders()
    orders.open_orders = [
        open_order(orders, fingerprint="a-different-cart", session_id=None, url=None)
    ]
    stripe = FakeStripeCheckout()

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert (orders.retired, orders.created, stripe.expired) == ([], [], [])


async def test_an_expired_unlinked_order_is_cancelled_without_a_stripe_call() -> None:
    orders = ready_orders()
    orders.open_orders = [
        open_order(orders, session_id=None, url=None, expires_at=PAST)
    ]
    stripe = FakeStripeCheckout()

    await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert orders.retired == ["old1"]
    assert stripe.expired == []


async def test_an_open_order_without_a_url_is_resumed_with_the_same_order() -> None:
    orders = ready_orders(order(item("mug", 1000, 2)))
    orders.open_orders = [
        open_order(orders, session_id=None, url=None, expires_at=RESUMABLE)
    ]
    stripe = FakeStripeCheckout()

    started = await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert orders.created == []
    assert stripe.requests[0].order_id == "order1"
    assert stripe.requests[0].expires_at == int(RESUMABLE.timestamp())
    assert orders.attached == [("order1", "cs_test_1")]
    assert started.checkout_url == "https://checkout.stripe.com/c/pay/cs_test_1"


async def test_losing_the_race_for_the_open_order_reuses_the_winner() -> None:
    orders = ready_orders()
    orders.create_errors = [OpenOrderExists()]
    orders.open_orders = [None, open_order(orders)]
    stripe = FakeStripeCheckout()

    started = await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert started.order_id == "old1"
    assert stripe.requests == []


async def test_giving_up_after_repeated_lost_races() -> None:
    orders = ready_orders()
    orders.create_errors = [OpenOrderExists()] * 3

    with pytest.raises(CheckoutUnavailable):
        await service(orders, FakeStripeCheckout()).start(SLUG, "tok", SUCCESS, CANCEL)


async def test_a_cart_with_no_live_row_cannot_check_out() -> None:
    orders = ready_orders()
    orders.cart_id = None

    with pytest.raises(CartNotReady):
        await service(orders, FakeStripeCheckout()).start(SLUG, "tok", SUCCESS, CANCEL)


def test_the_fingerprint_changes_with_lines_totals_and_urls() -> None:
    base = cart(cart_line("v-mug", 1000, 2))
    reference = checkout_fingerprint(base, "GBP", SUCCESS, CANCEL)

    assert reference == checkout_fingerprint(base, "GBP", SUCCESS, CANCEL)
    assert reference != checkout_fingerprint(
        cart(cart_line("v-mug", 1000, 3)), "GBP", SUCCESS, CANCEL
    )
    assert reference != checkout_fingerprint(
        cart(cart_line("v-mug", 1100, 2)), "GBP", SUCCESS, CANCEL
    )
    assert reference != checkout_fingerprint(base, "USD", SUCCESS, CANCEL)
    assert reference != checkout_fingerprint(base, "GBP", CANCEL, SUCCESS)


async def test_losing_a_cancel_after_expiring_the_old_session_starts_nothing() -> None:
    orders = ready_orders()
    orders.open_orders = [open_order(orders, fingerprint="a-different-cart")]
    stripe = FakeStripeCheckout()

    async def lost(order_id: str) -> bool:
        return False  # paid or cancelled by someone else in between

    orders.cancel_pending = lost  # type: ignore[method-assign]

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert (orders.created, stripe.requests) == ([], [])


async def test_a_failed_sweep_is_logged_and_rolled_back_not_raised() -> None:
    session = BrokenSession()

    await sql_orders(session).sweep()

    assert session.rollbacks == 1


async def test_a_failed_pending_cancel_is_rolled_back_and_raised() -> None:
    session = BrokenSession()

    with pytest.raises(RuntimeError):
        await sql_orders(session).cancel_pending("order1")

    assert session.rollbacks == 1


async def test_a_purged_cart_is_a_changed_cart_and_other_violations_propagate() -> None:
    def violation(constraint: str) -> IntegrityError:
        return IntegrityError("INSERT", {}, Exception(f"violates {constraint}"))

    async def priced(*args: Any, **kwargs: Any) -> OrderRecord:
        return order(item("mug", 1000, 1))

    origin = CheckoutOrigin("cart1", "fp", FUTURE)
    lines = [OrderLineInput("v-mug", 1)]
    for constraint, expected in (
        ("uq_orders_open_checkout_per_cart", OpenOrderExists),
        ("fk_orders_cart", InvalidOrder),
        ("something_else", IntegrityError),
    ):
        session = FailingInsertSession(violation(constraint))
        orders = SqlCheckoutOrders(session, None, StubSettings())  # type: ignore[arg-type]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(store_checkout, "price_checkout_order", priced)
            with pytest.raises(expected):
                await orders.create_order(lines, "GBP", origin)
        assert session.rollbacks == 1


class StubSettings:
    async def totals_settings(self) -> Any:
        return None


class FailingInsertSession:
    def __init__(self, error: IntegrityError) -> None:
        self.error = error
        self.rollbacks = 0

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error

    async def commit(self) -> None:
        raise AssertionError("nothing to commit")

    async def rollback(self) -> None:
        self.rollbacks += 1


async def test_an_open_session_about_to_end_is_not_handed_out_again() -> None:
    orders = ready_orders()
    orders.open_orders = [open_order(orders, expires_at=ENDING)]
    stripe = FakeStripeCheckout()

    started = await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert stripe.expired == [(ACCOUNT, "cs_old")]
    assert orders.retired == ["old1"]
    assert started.order_id == "order1"


async def test_a_session_less_order_too_close_to_its_end_is_not_resumed() -> None:
    # Stripe would refuse an expiry under 30 minutes ahead, and the order may have a session.
    orders = ready_orders()
    orders.open_orders = [
        open_order(orders, session_id=None, url=None, expires_at=FUTURE)
    ]
    stripe = FakeStripeCheckout()

    with pytest.raises(CheckoutUnavailable):
        await service(orders, stripe).start(SLUG, "tok", SUCCESS, CANCEL)

    assert (stripe.requests, stripe.expired, orders.retired) == ([], [], [])


@pytest.mark.parametrize("permutation", list(itertools.permutations(range(3))), ids=str)
def test_line_items_do_not_depend_on_the_order_of_the_stored_lines(
    permutation: tuple[int, ...],
) -> None:
    items = [item("mug", 1000, 2), item("cap", 550, 1), item("pin", 10, 1)]
    reference = build_session_request(target(), order(*items), SUCCESS, CANCEL, FUTURE)

    shuffled = build_session_request(
        target(), order(*(items[i] for i in permutation)), SUCCESS, CANCEL, FUTURE
    )

    assert shuffled == reference
    assert [li.name for li in reference.line_items] == ["cap", "mug", "pin"]
