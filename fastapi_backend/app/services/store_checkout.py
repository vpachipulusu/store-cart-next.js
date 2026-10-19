"""Storefront checkout on the merchant's connected account (KAN-68). No FastAPI imports.

``StoreCheckoutService.start`` turns the shopper's cart into a ``pending`` order and a Stripe
Checkout Session:

1. The store (ACTIVE, by slug) and its organisation's Connect state are read on the platform
   database. Checkout is refused (``PaymentsNotEnabled``) unless the organisation has a
   connected account with charges enabled (the KAN-67 guard), before anything is written.
2. The cart must be checkout-ready (every line sellable and in stock). The order is priced
   **only on the server**, in integer minor units: lines are re-read from the catalogue under a
   share lock and the totals come from ``compute_totals`` with the store's shipping and tax
   settings. The request can name nothing but its return URLs.
3. The session is a **direct charge** on the connected account (``Stripe-Account``) whose line
   items add up exactly to the order total. ``application_fee_amount`` comes from the
   organisation's ``platform_fee_bps`` (0 by default, then the field is not sent). The
   idempotency key is derived from the order id on the server, so a retried Stripe call cannot
   create a second session for one order. If Stripe fails, the order is cancelled.

``confirm_checkout_payment`` is the Connect webhook side (``checkout.session.completed`` and
``checkout.session.async_payment_succeeded``): it marks the order paid in the store database
with one conditional update keyed on the order and the unique session id, so the at-least-once
store side effect is idempotent under duplicate and concurrent deliveries.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionProvider
from app.core.ids import new_id
from app.core.slugs import InvalidSlug, ReservedSlug, normalize_slug
from app.core.stripe_billing import StripeError
from app.core.stripe_checkout import (
    CheckoutLineItem,
    CheckoutSessionRequest,
    StripeCheckout,
)
from app.repositories.app_settings import AppSettingsRepository
from app.repositories.checkout import CheckoutRepository
from app.repositories.connect_events import ConnectRoute
from app.repositories.org_connect import ConnectRecord
from app.services.org_billing import InvalidReturnUrl, validate_return_url
from app.services.public_settings import PublicSettingsService
from app.services.store_cart import CartView
from app.services.store_orders import (
    BPS_DENOMINATOR,
    InvalidOrder,
    OrderItemRecord,
    OrderLineInput,
    OrderRecord,
    OrderStatus,
    PaymentOutcome,
    insert_order,
    link_checkout_session,
    load_catalogue,
    mark_checkout_paid,
    transition_order,
    validate_order_input,
)
from app.services.store_totals import (
    LineAmount,
    TotalsSettings,
    compute_totals,
    line_tax,
)
from app.services.stripe_connect import (
    ChargesNotEnabled,
    StoreEventHandler,
    require_charges_enabled,
)

logger = logging.getLogger(__name__)

COMPLETED_EVENT_TYPE = "checkout.session.completed"
ASYNC_SUCCEEDED_EVENT_TYPE = "checkout.session.async_payment_succeeded"
PAYMENT_EVENT_TYPES = (COMPLETED_EVENT_TYPE, ASYNC_SUCCEEDED_EVENT_TYPE)
MAX_FEE_BPS = BPS_DENOMINATOR  # 100%
TAX_LINE_NAME = "Tax"
SHIPPING_LINE_NAME = "Shipping"
PAID_STATUS = "paid"
CART_CHANGED = "Your cart has changed. Review it and try again."
SESSION_ID_PATTERN = re.compile(r"cs_[A-Za-z0-9_]{1,250}")
PAYMENT_INTENT_PATTERN = re.compile(r"pi_[A-Za-z0-9_]{1,250}")
ORDER_ID_PATTERN = re.compile(r"[A-Za-z0-9]{1,64}")
CURRENCY_PATTERN = re.compile(r"[a-z]{3}")


class CheckoutError(Exception):
    """A checkout that cannot start. The message is safe to show the shopper."""


class CheckoutStoreNotFound(CheckoutError):
    def __init__(self) -> None:
        super().__init__("Store not found")


class PaymentsNotEnabled(CheckoutError):
    def __init__(self) -> None:
        super().__init__("Payments are not enabled for this store")


class CartNotReady(CheckoutError):
    """The cart is empty, changed since it was shown, or has nothing to pay (HTTP 409)."""


class InvalidCheckoutUrl(CheckoutError):
    def __init__(self) -> None:
        super().__init__("Return URL is not allowed")


class CheckoutUnavailable(CheckoutError):
    def __init__(self) -> None:
        super().__init__("Payment could not be started. Try again.")


@dataclass(frozen=True)
class CheckoutTarget:
    store_id: str
    slug: str
    connect: ConnectRecord
    platform_fee_bps: int
    currency: str  # upper-case ISO 4217 (the platform currency setting)


@dataclass(frozen=True)
class CheckoutStarted:
    order_id: str
    checkout_url: str


class CheckoutTargets(Protocol):
    async def find(self, slug: str) -> CheckoutTarget | None: ...


class CheckoutOrders(Protocol):
    """One store database. Every write commits before it returns."""

    async def view_cart(self, token: str | None) -> CartView: ...

    async def create_order(
        self, lines: Sequence[OrderLineInput], currency: str
    ) -> OrderRecord: ...

    async def attach_session(self, order_id: str, session_id: str) -> None: ...

    async def cancel_order(self, order_id: str) -> None: ...


OpenOrders = Callable[[str], AbstractAsyncContextManager[CheckoutOrders]]


def platform_fee_minor(total_minor: int, fee_bps: int) -> int:
    """The platform's application fee on ``total_minor``, rounded half up (integers only)."""
    if isinstance(fee_bps, bool) or not 0 <= fee_bps <= MAX_FEE_BPS:
        raise ValueError("platform_fee_bps must be between 0 and 10000")
    return (total_minor * fee_bps + BPS_DENOMINATOR // 2) // BPS_DENOMINATOR


def checkout_return_origins(origins: frozenset[str], slug: str) -> frozenset[str]:
    """Allowed return origins: the configured app origins and the store's own subdomain of each.

    ``https://www.example.com`` also allows ``https://{slug}.example.com`` (the leading
    ``www.`` is the app host, not the root domain).
    """
    allowed = set(origins)
    for origin in origins:
        parts = urlsplit(origin)
        host = parts.hostname
        if not host:
            continue
        root = host.removeprefix("www.")
        port = f":{parts.port}" if parts.port else ""
        allowed.add(f"{parts.scheme}://{slug}.{root}{port}")
    return frozenset(allowed)


def _line_name(item: OrderItemRecord) -> str:
    if item.variant_label:
        return f"{item.product_name} ({item.variant_label})"
    return item.product_name


def build_session_request(
    target: CheckoutTarget, order: OrderRecord, success_url: str, cancel_url: str
) -> CheckoutSessionRequest:
    """The Checkout Session for ``order``: items, then tax added on top, then shipping."""
    account_id = target.connect.stripe_connect_account_id
    if account_id is None:
        raise ValueError("the organisation has no connected account")
    items = [
        CheckoutLineItem(_line_name(item), item.unit_price_minor, item.quantity)
        for item in order.items
    ]
    if order.tax_minor and not order.prices_include_tax:
        items.append(CheckoutLineItem(TAX_LINE_NAME, order.tax_minor, 1))
    if order.shipping_minor:
        items.append(CheckoutLineItem(SHIPPING_LINE_NAME, order.shipping_minor, 1))
    if sum(i.unit_amount_minor * i.quantity for i in items) != order.total_minor:
        raise ValueError("the line items do not add up to the order total")
    fee = platform_fee_minor(order.total_minor, target.platform_fee_bps)
    return CheckoutSessionRequest(
        account_id=account_id,
        currency=order.currency.lower(),
        line_items=tuple(items),
        application_fee_minor=fee or None,
        store_id=target.store_id,
        order_id=order.id,
        success_url=success_url,
        cancel_url=cancel_url,
        idempotency_key=f"sc-checkout-{target.store_id}-{order.id}",
    )


async def price_checkout_order(
    session: AsyncSession,
    *,
    currency: str,
    lines: Sequence[OrderLineInput],
    settings: TotalsSettings,
) -> OrderRecord:
    """A ``pending`` order priced from the catalogue (share-locked) and the store settings."""
    validate_order_input(currency, settings.tax_rate_bps, lines)
    catalogue = await load_catalogue(session, lines)
    items: list[OrderItemRecord] = []
    for line in lines:
        row = catalogue[line.variant_id]
        amount = LineAmount(row["price_minor"], line.quantity)
        items.append(
            OrderItemRecord(
                id=new_id(),
                product_id=row["product_id"],
                variant_id=line.variant_id,
                product_name=row["product_name"],
                sku=row["sku"],
                variant_label=row["variant_label"],
                unit_price_minor=amount.unit_price_minor,
                quantity=line.quantity,
                tax_rate_bps=settings.tax_rate_bps,
                tax_minor=line_tax(amount, settings),
            )
        )
    try:
        totals = compute_totals(
            [LineAmount(i.unit_price_minor, i.quantity) for i in items], settings
        )
    except ValueError:
        raise InvalidOrder("The order total is too large") from None
    return OrderRecord(
        id=new_id(),
        status=OrderStatus.PENDING,
        currency=currency,
        subtotal_minor=totals.subtotal_minor,
        tax_minor=totals.tax_minor,
        total_minor=totals.total_minor,
        items=tuple(items),
        shipping_minor=totals.shipping_minor,
        prices_include_tax=totals.prices_include_tax,
    )


class CartReader(Protocol):
    async def view(self, token: str | None) -> CartView: ...


class SettingsReader(Protocol):
    async def totals_settings(self) -> TotalsSettings: ...


class SqlCheckoutOrders:
    """``CheckoutOrders`` on one store session (the caller opens and closes it)."""

    def __init__(
        self, session: AsyncSession, cart: CartReader, settings: SettingsReader
    ) -> None:
        self._session = session
        self._cart = cart
        self._settings = settings

    async def view_cart(self, token: str | None) -> CartView:
        return await self._cart.view(token)

    async def create_order(
        self, lines: Sequence[OrderLineInput], currency: str
    ) -> OrderRecord:
        settings = await self._settings.totals_settings()
        order = await price_checkout_order(
            self._session, currency=currency, lines=lines, settings=settings
        )
        await insert_order(self._session, order)
        await self._session.commit()
        return order

    async def attach_session(self, order_id: str, session_id: str) -> None:
        await link_checkout_session(self._session, order_id, session_id)
        await self._session.commit()

    async def cancel_order(self, order_id: str) -> None:
        """Best effort: a failure here must not hide why the checkout stopped."""
        try:
            await transition_order(self._session, order_id, OrderStatus.CANCELLED)
            await self._session.commit()
        except Exception as exc:  # noqa: BLE001 - the original failure is the one to report
            logger.warning(
                "unstarted checkout order not cancelled: %s", type(exc).__name__
            )
            await self._session.rollback()


class PlatformCheckoutTargets:
    """``CheckoutTargets`` on the platform database; the connection is released before returning."""

    def __init__(self, provider: SessionProvider) -> None:
        self._provider = provider

    async def find(self, slug: str) -> CheckoutTarget | None:
        try:
            normalized = normalize_slug(slug)
        except (InvalidSlug, ReservedSlug):
            return None
        async with self._provider.session() as session:
            row = await CheckoutRepository(session).find_active_store(normalized)
            if row is None:
                return None
            currency = await PublicSettingsService(
                AppSettingsRepository(session)
            ).currency()
        return CheckoutTarget(
            store_id=row.store_id,
            slug=row.slug,
            connect=row.connect,
            platform_fee_bps=row.platform_fee_bps,
            currency=currency,
        )


class StoreCheckoutService:
    def __init__(
        self,
        targets: CheckoutTargets,
        open_orders: OpenOrders,
        stripe: StripeCheckout,
        origins: frozenset[str],
    ) -> None:
        self._targets = targets
        self._open_orders = open_orders
        self._stripe = stripe
        self._origins = origins

    async def start(
        self, slug: str, token: str | None, success_url: str, cancel_url: str
    ) -> CheckoutStarted:
        target = await self._targets.find(slug)
        if target is None:
            raise CheckoutStoreNotFound
        allowed = checkout_return_origins(self._origins, target.slug)
        success = _return_url(success_url, allowed)
        cancel = _return_url(cancel_url, allowed)
        try:
            require_charges_enabled(target.connect)
        except ChargesNotEnabled:
            raise PaymentsNotEnabled from None
        async with self._open_orders(target.store_id) as orders:
            order = await self._create_order(orders, token, target.currency)
            request = build_session_request(target, order, success, cancel)
            try:
                created = await self._stripe.create_payment_session(request)
            except StripeError:
                await orders.cancel_order(order.id)
                raise CheckoutUnavailable from None
            await orders.attach_session(order.id, created.id)
        return CheckoutStarted(order_id=order.id, checkout_url=created.url)

    async def _create_order(
        self, orders: CheckoutOrders, token: str | None, currency: str
    ) -> OrderRecord:
        view = await orders.view_cart(token)
        if not view.lines or not view.can_checkout:
            raise CartNotReady(CART_CHANGED)
        lines = [OrderLineInput(line.variant_id, line.quantity) for line in view.lines]
        try:
            order = await orders.create_order(lines, currency)
        except InvalidOrder:
            raise CartNotReady(CART_CHANGED) from None
        if order.total_minor <= 0:
            await orders.cancel_order(order.id)
            raise CartNotReady("There is nothing to pay for.")
        return order


def _return_url(url: str, allowed: frozenset[str]) -> str:
    try:
        return validate_return_url(url, allowed)
    except InvalidReturnUrl:
        raise InvalidCheckoutUrl from None


@dataclass(frozen=True)
class _PaidSession:
    session_id: str
    order_id: str
    payment_intent_id: str | None
    amount_minor: int
    currency: str


def _paid_session(obj: Mapping[str, Any]) -> _PaidSession | None:
    """The fields a paid Checkout Session must carry, or None when any is missing or odd."""
    metadata = obj.get("metadata")
    order_id = metadata.get("order_id") if isinstance(metadata, Mapping) else None
    session_id = obj.get("id")
    amount = obj.get("amount_total")
    currency = obj.get("currency")
    payment_intent = obj.get("payment_intent")
    if not (
        isinstance(session_id, str)
        and SESSION_ID_PATTERN.fullmatch(session_id)
        and isinstance(order_id, str)
        and ORDER_ID_PATTERN.fullmatch(order_id)
        and isinstance(amount, int)
        and not isinstance(amount, bool)
        and amount > 0
        and isinstance(currency, str)
        and CURRENCY_PATTERN.fullmatch(currency)
    ):
        return None
    intent = (
        payment_intent
        if isinstance(payment_intent, str)
        and PAYMENT_INTENT_PATTERN.fullmatch(payment_intent)
        else None
    )
    return _PaidSession(session_id, order_id, intent, amount, currency.upper())


async def confirm_checkout_payment(
    session: AsyncSession, obj: Mapping[str, Any]
) -> PaymentOutcome | None:
    """Mark the session's order paid, at most once. Does not commit.

    None when there is nothing to do yet (not paid, for example a delayed payment method) or
    the object is unusable. A session that does not match a pending order is logged as an
    error and changes nothing: a paid session for a cancelled order needs a manual refund.
    """
    if obj.get("payment_status") != PAID_STATUS:
        logger.info("checkout session not paid yet")
        return None
    paid = _paid_session(obj)
    if paid is None:
        logger.warning("paid checkout session without usable fields")
        return None
    outcome = await mark_checkout_paid(
        session,
        order_id=paid.order_id,
        session_id=paid.session_id,
        payment_intent_id=paid.payment_intent_id,
        amount_minor=paid.amount_minor,
        currency=paid.currency,
    )
    if outcome in (PaymentOutcome.MISMATCH, PaymentOutcome.NOT_FOUND):
        logger.error(
            "paid checkout session does not match a pending order: %s",
            outcome.value,
            extra={"order_id": paid.order_id},
        )
    else:
        logger.info(
            "checkout payment confirmed: %s",
            outcome.value,
            extra={"order_id": paid.order_id},
        )
    return outcome


def checkout_payment_handler(
    open_store: Callable[[str], AbstractAsyncContextManager[AsyncSession]],
) -> StoreEventHandler:
    """The Connect webhook handler for ``PAYMENT_EVENT_TYPES``.

    Runs inside the platform claim's transaction and commits only the store session it opens:
    the write is idempotent (``mark_checkout_paid``), so Stripe's retry after a failed claim
    changes nothing.
    """

    async def handle(route: ConnectRoute, obj: Mapping[str, Any]) -> None:
        if route.store_id is None:  # store-scoped events always carry one
            return
        async with open_store(route.store_id) as session:
            await confirm_checkout_payment(session, obj)
            await session.commit()

    return handle
