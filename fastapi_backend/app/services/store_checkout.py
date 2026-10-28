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
   organisation's ``platform_fee_bps`` (0 by default, then the field is not sent), on the
   amount charged. The idempotency key is derived from the order id on the server. A request
   Stripe did not process (4xx: refused, 401, 429) cancels the order. An unknown outcome
   (timeout, transport error, 5xx, 409) is retried once with the same key: after a timeout that
   returns the session Stripe may already have made instead of a second one (a 5xx is usually
   replayed as is). If it stays unknown the order is left ``pending`` (the webhook can still pay
   it). Any failure while building the request after the order was written cancels it too.

One open order per cart (KAN-256): a cart has at most one ``pending`` checkout order (a partial
unique index enforces it). Starting again for an unchanged cart (same lines, prices, totals and
return URLs: the order's fingerprint) returns the open session's URL without a new order or
session; if the first start never learned its session, it is created again with the same
idempotency key, so Stripe hands back the one it made. A changed cart first expires the old
session at Stripe, then cancels the old order, then writes the new one: a session that may
still be payable is never left behind a cancelled order. Sessions carry an explicit
``expires_at`` (``store_checkout_expiry``), which also ends orders whose shopper walked away.

``confirm_checkout_payment`` is the Connect webhook side (``checkout.session.completed`` and
``checkout.session.async_payment_succeeded``): it marks the order paid in the store database
with one conditional update keyed on the order and the unique session id, so the at-least-once
store side effect is idempotent under duplicate and concurrent deliveries.
"""

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionProvider
from app.core.ids import new_id
from app.core.sentry import report_exception
from app.core.slugs import InvalidSlug, ReservedSlug, normalize_slug
from app.core.stripe_billing import (
    StripeConflict,
    StripeError,
    StripeForbidden,
    StripeNotFound,
    StripeNotProcessed,
    StripeRejected,
)
from app.core.stripe_checkout import (
    CheckoutLineItem,
    CheckoutSessionRequest,
    ExpireOutcome,
    StripeCheckout,
    StripeCheckoutSession,
)
from app.repositories.app_settings import AppSettingsRepository
from app.repositories.checkout import CheckoutRepository
from app.repositories.connect_events import ConnectRoute
from app.repositories.org_connect import ConnectRecord
from app.repositories.store_cart import StoreCartRepository
from app.services.order_email_job import (
    PAID_KINDS,
    OrderEmailEnqueuer,
    clean_customer_email,
    pending_jobs,
    publish_jobs,
    record_order_emails,
)
from app.services.org_billing import InvalidReturnUrl, validate_return_url
from app.services.public_settings import PublicSettingsService
from app.services.store_cart import CartView, hash_token, valid_token
from app.services.store_checkout_expiry import (
    RESUME_MIN_REMAINING,
    REUSE_MARGIN,
    SESSION_LIFETIME,
    START_SWEEP_BATCH,
    sweep_expired_checkout_orders,
)
from app.services.store_orders import (
    BPS_DENOMINATOR,
    CheckoutOrigin,
    InvalidOrder,
    OpenCheckout,
    OrderItemRecord,
    OrderLineInput,
    OrderRecord,
    OrderStatus,
    PaymentOutcome,
    cancel_pending_order,
    find_open_checkout,
    insert_order,
    link_checkout_session,
    load_catalogue,
    load_order,
    mark_checkout_paid,
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
SESSION_ATTEMPTS = 2
OPEN_ORDER_ATTEMPTS = 3  # lost races for the cart's one open order before giving up
OPEN_CHECKOUT_INDEX = "uq_orders_open_checkout_per_cart"
CART_FOREIGN_KEY = "fk_orders_cart"
CONFLICT_RETRY_DELAY_SECONDS = 0.5
ROOT_DOMAIN_PATTERN = re.compile(
    r"(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*"
)
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


class PaymentInProgress(CheckoutError):
    """The cart's earlier checkout was paid or is being paid (HTTP 409)."""

    def __init__(self) -> None:
        super().__init__("Your payment is being processed. Check back in a moment.")


class OpenOrderExists(Exception):
    """The cart already has a pending order (the unique index said so)."""


class UnappliedCheckoutPayment(Exception):
    """A paid Checkout Session that changed no order: money taken, order not paid (Sentry only)."""


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

    async def sweep(self) -> None:
        """Best effort: cancel a few of this store's expired orders that have no session."""
        ...

    async def find_cart(self, token: str | None) -> str | None: ...

    async def find_open_checkout(self, cart_id: str) -> OpenCheckout | None: ...

    async def load_order(self, order_id: str) -> OrderRecord: ...

    async def create_order(
        self, lines: Sequence[OrderLineInput], currency: str, origin: CheckoutOrigin
    ) -> OrderRecord:
        """Raises ``OpenOrderExists`` when the cart already has a pending order."""
        ...

    async def attach_session(
        self, order_id: str, session_id: str, url: str
    ) -> None: ...

    async def cancel_order(self, order_id: str) -> None: ...

    async def cancel_pending(self, order_id: str) -> bool:
        """Cancel a pending order and report whether it was (errors propagate)."""
        ...


OpenOrders = Callable[[str], AbstractAsyncContextManager[CheckoutOrders]]


def platform_fee_minor(total_minor: int, fee_bps: int) -> int:
    """The platform's application fee on ``total_minor``, rounded half up (integers only)."""
    if isinstance(fee_bps, bool) or not 0 <= fee_bps <= MAX_FEE_BPS:
        raise ValueError("platform_fee_bps must be between 0 and 10000")
    return (total_minor * fee_bps + BPS_DENOMINATOR // 2) // BPS_DENOMINATOR


def normalize_root_domain(value: str | None) -> str | None:
    """The platform root domain as a lower-case host name, or None when unset or invalid."""
    if value is None:
        return None
    host = value.strip().lower().rstrip(".")
    return host if ROOT_DOMAIN_PATTERN.fullmatch(host) else None


def checkout_return_origins(
    origins: frozenset[str], slug: str, root_domain: str | None
) -> frozenset[str]:
    """Allowed return origins: the app origins, and the store's own host ``{slug}.<root>``.

    Store subdomains live under the platform root domain (``PLATFORM_ROOT_DOMAIN``), not under
    the app's host. The store host is allowed over https, and also with the scheme and port of
    any app origin on the root domain or below it (``http://localhost:3000`` with root
    ``localhost`` allows ``http://{slug}.localhost:3000`` in development).
    """
    allowed = set(origins)
    root = normalize_root_domain(root_domain)
    if root is None:
        return frozenset(allowed)
    store_host = f"{slug}.{root}"
    allowed.add(f"https://{store_host}")
    for origin in origins:
        parts = urlsplit(origin)
        host = parts.hostname
        if host is None or not (host == root or host.endswith(f".{root}")):
            continue
        port = f":{parts.port}" if parts.port else ""
        allowed.add(f"{parts.scheme}://{store_host}{port}")
    return frozenset(allowed)


def _line_name(item: OrderItemRecord) -> str:
    if item.variant_label:
        return f"{item.product_name} ({item.variant_label})"
    return item.product_name


def build_session_request(
    target: CheckoutTarget,
    order: OrderRecord,
    success_url: str,
    cancel_url: str,
    expires_at: datetime | None = None,
) -> CheckoutSessionRequest:
    """The Checkout Session for ``order``: items, then tax added on top, then shipping."""
    account_id = target.connect.stripe_connect_account_id
    if account_id is None:
        raise ValueError("the organisation has no connected account")
    # A stable order: a replay of an unlinked order (same idempotency key) is rebuilt from the
    # database, and Stripe refuses a key whose parameters differ.
    ordered = sorted(
        order.items, key=lambda i: (i.variant_id or "", i.product_name, i.sku)
    )
    items = [
        CheckoutLineItem(_line_name(item), item.unit_price_minor, item.quantity)
        for item in ordered
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
        expires_at=int(expires_at.timestamp()) if expires_at else None,
    )


def checkout_fingerprint(
    view: CartView, currency: str, success_url: str, cancel_url: str
) -> str:
    """What an open session was built for; the same value means it can be reused as is."""
    lines = sorted(
        f"{line.variant_id}:{line.quantity}:{line.unit_price_minor}"
        for line in view.lines
    )
    parts = [currency, str(view.totals.total_minor), success_url, cancel_url, *lines]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


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

    async def sweep(self) -> None:
        try:
            await sweep_expired_checkout_orders(
                self._session,
                None,
                None,
                batch=START_SWEEP_BATCH,
                with_sessions=False,
            )
        except Exception as exc:  # noqa: BLE001 - the sweep must never stop a checkout
            logger.error("checkout expiry sweep failed: %s", type(exc).__name__)
            await self._rollback_quietly()

    async def find_cart(self, token: str | None) -> str | None:
        if token is None or not valid_token(token):
            return None
        cart_id = await StoreCartRepository(self._session).find_live_cart(
            hash_token(token)
        )
        await self._session.rollback()
        return cart_id

    async def find_open_checkout(self, cart_id: str) -> OpenCheckout | None:
        found = await find_open_checkout(self._session, cart_id)
        await self._session.rollback()  # no transaction open across Stripe calls
        return found

    async def load_order(self, order_id: str) -> OrderRecord:
        order = await load_order(self._session, order_id)
        await self._session.rollback()
        return order

    async def create_order(
        self, lines: Sequence[OrderLineInput], currency: str, origin: CheckoutOrigin
    ) -> OrderRecord:
        settings = await self._settings.totals_settings()
        order = await price_checkout_order(
            self._session, currency=currency, lines=lines, settings=settings
        )
        try:
            await insert_order(self._session, order, origin)
            await self._session.commit()
        except IntegrityError as error:
            await self._rollback_quietly()
            if OPEN_CHECKOUT_INDEX in str(error.orig):
                raise OpenOrderExists from None
            if CART_FOREIGN_KEY in str(error.orig):  # the cart expired and was purged
                raise InvalidOrder("The cart is gone") from None
            raise
        return order

    async def cancel_pending(self, order_id: str) -> bool:
        try:
            cancelled = await cancel_pending_order(self._session, order_id)
            await self._session.commit()
        except Exception:
            await self._rollback_quietly()
            raise
        return cancelled

    async def attach_session(self, order_id: str, session_id: str, url: str) -> None:
        """Best effort: the webhook also accepts an order with no session linked yet.

        So a failure here must not cost the shopper the checkout URL Stripe already made.
        """
        try:
            linked = await link_checkout_session(
                self._session, order_id, session_id, url
            )
            await self._session.commit()
        except Exception as exc:  # noqa: BLE001 - logged; the webhook can still link it
            logger.error(
                "checkout session not linked to its order: %s",
                type(exc).__name__,
                extra={"order_id": order_id},
            )
            await self._rollback_quietly()
            return
        if not linked:  # the webhook got there first, or another session is linked
            logger.warning(
                "checkout session not linked: order not pending or already linked",
                extra={"order_id": order_id},
            )

    async def cancel_order(self, order_id: str) -> None:
        """Best effort: a failure here must not hide why the checkout stopped."""
        try:
            await cancel_pending_order(self._session, order_id)
            await self._session.commit()
        except Exception as exc:  # noqa: BLE001 - the original failure is the one to report
            logger.error(
                "unstarted checkout order not cancelled: %s",
                type(exc).__name__,
                extra={"order_id": order_id},
            )
            await self._rollback_quietly()

    async def _rollback_quietly(self) -> None:
        try:
            await self._session.rollback()
        except Exception as exc:  # noqa: BLE001 - a dead connection must not mask the cause
            logger.warning("store rollback failed: %s", type(exc).__name__)


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
        root_domain: str | None,
        *,
        conflict_delay: float = CONFLICT_RETRY_DELAY_SECONDS,
    ) -> None:
        self._targets = targets
        self._open_orders = open_orders
        self._stripe = stripe
        self._origins = origins
        self._root_domain = root_domain
        self._conflict_delay = conflict_delay

    async def start(
        self, slug: str, token: str | None, success_url: str, cancel_url: str
    ) -> CheckoutStarted:
        target = await self._targets.find(slug)
        if target is None:
            raise CheckoutStoreNotFound
        allowed = checkout_return_origins(self._origins, target.slug, self._root_domain)
        success = _return_url(success_url, allowed)
        cancel = _return_url(cancel_url, allowed)
        try:
            require_charges_enabled(target.connect)
        except ChargesNotEnabled:
            raise PaymentsNotEnabled from None
        _check_fee_rate(target)
        async with self._open_orders(target.store_id) as orders:
            await orders.sweep()
            view = await orders.view_cart(token)
            if not view.lines or not view.can_checkout:
                raise CartNotReady(CART_CHANGED)
            cart_id = await orders.find_cart(token)
            if cart_id is None:
                raise CartNotReady(CART_CHANGED)
            fingerprint = checkout_fingerprint(view, target.currency, success, cancel)
            for _ in range(OPEN_ORDER_ATTEMPTS):
                open_checkout = await orders.find_open_checkout(cart_id)
                if open_checkout is not None:
                    reused = await self._reuse_or_retire(
                        target, orders, open_checkout, fingerprint, success, cancel
                    )
                    if reused is not None:
                        return reused
                expires_at = datetime.now(UTC) + SESSION_LIFETIME
                origin = CheckoutOrigin(cart_id, fingerprint, expires_at)
                try:
                    order = await self._create_order(orders, view, target, origin)
                except OpenOrderExists:
                    continue  # lost a race for the cart's one open order: look again
                return await self._open_session(
                    target, orders, order, success, cancel, expires_at
                )
        raise CheckoutUnavailable

    async def _reuse_or_retire(
        self,
        target: CheckoutTarget,
        orders: CheckoutOrders,
        open_checkout: OpenCheckout,
        fingerprint: str,
        success: str,
        cancel: str,
    ) -> CheckoutStarted | None:
        """The open order's checkout when it still fits the cart; None once it is retired."""
        expires_at = open_checkout.expires_at
        remaining = expires_at - datetime.now(UTC) if expires_at else None
        live = remaining is not None and remaining > timedelta(0)
        if (
            expires_at is not None
            and remaining is not None
            and open_checkout.fingerprint == fingerprint
        ):
            if open_checkout.url is not None and remaining > REUSE_MARGIN:
                return CheckoutStarted(open_checkout.order_id, open_checkout.url)
            if open_checkout.url is None and remaining >= RESUME_MIN_REMAINING:
                # The first start never learned its session: ask for it again. The
                # idempotency key and ``expires_at`` are the order's, so Stripe returns the
                # session it may already have made.
                order = await orders.load_order(open_checkout.order_id)
                return await self._open_session(
                    target, orders, order, success, cancel, expires_at
                )
        await self._retire(target, orders, open_checkout, live=live)
        return None

    async def _retire(
        self,
        target: CheckoutTarget,
        orders: CheckoutOrders,
        open_checkout: OpenCheckout,
        *,
        live: bool,
    ) -> None:
        """Make the open order's session unpayable, then cancel the order, in that order.

        Cancelling first could leave a payable session behind a cancelled order. An order
        whose session is unknown while its expiry has not passed may still have one at Stripe,
        so it is neither cancelled nor replaced until it expires.
        """
        account_id = target.connect.stripe_connect_account_id
        if open_checkout.session_id is not None and account_id is not None:
            try:
                outcome = await self._stripe.expire_session(
                    account_id, open_checkout.session_id
                )
            except StripeError:
                logger.warning(
                    "open checkout session not expired; checkout refused",
                    extra={"order_id": open_checkout.order_id},
                )
                raise CheckoutUnavailable from None
            if outcome is ExpireOutcome.COMPLETE:
                raise PaymentInProgress
        elif live:
            raise CheckoutUnavailable
        if not await orders.cancel_pending(open_checkout.order_id):
            # Paid or cancelled by someone else since the read: never start a second order
            # on top of that. The shopper retries and sees the settled state.
            raise CheckoutUnavailable

    async def _open_session(
        self,
        target: CheckoutTarget,
        orders: CheckoutOrders,
        order: OrderRecord,
        success: str,
        cancel: str,
        expires_at: datetime,
    ) -> CheckoutStarted:
        try:
            request = build_session_request(target, order, success, cancel, expires_at)
        except ValueError as exc:
            # Written but unpayable: never leave it pending.
            logger.error(
                "checkout request could not be built: %s",
                exc,
                extra={"order_id": order.id},
            )
            await orders.cancel_order(order.id)
            raise CheckoutUnavailable from None
        created = await self._create_session(orders, order.id, request)
        await orders.attach_session(order.id, created.id, created.url)
        return CheckoutStarted(order_id=order.id, checkout_url=created.url)

    async def _create_session(
        self, orders: CheckoutOrders, order_id: str, request: CheckoutSessionRequest
    ) -> StripeCheckoutSession:
        """Create the session. A definite refusal cancels the order; an unknown outcome retries.

        The retry sends the same idempotency key. After a timeout or transport error Stripe
        answers with the session it may already have created; after a 409 (in flight) it waits
        a moment first; a 5xx is usually replayed as is. If the outcome is still unknown, the
        order stays pending: a cancelled order with a live session could be paid and then never
        confirmed.
        """
        for attempt in range(SESSION_ATTEMPTS):
            try:
                return await self._stripe.create_payment_session(request)
            except StripeConflict:
                # In flight: unknown outcome; give the first request time to finish.
                if attempt < SESSION_ATTEMPTS - 1:
                    await asyncio.sleep(self._conflict_delay)
            except (
                StripeRejected,
                StripeNotProcessed,
                StripeForbidden,
                StripeNotFound,
            ):
                await orders.cancel_order(order_id)
                raise CheckoutUnavailable from None
            except StripeError:
                pass  # timeout, transport error or 5xx: unknown outcome
            if attempt == SESSION_ATTEMPTS - 1:
                logger.warning(
                    "checkout session outcome unknown; order left pending",
                    extra={"order_id": order_id},
                )
        raise CheckoutUnavailable

    async def _create_order(
        self,
        orders: CheckoutOrders,
        view: CartView,
        target: CheckoutTarget,
        origin: CheckoutOrigin,
    ) -> OrderRecord:
        lines = [OrderLineInput(line.variant_id, line.quantity) for line in view.lines]
        try:
            order = await orders.create_order(lines, target.currency, origin)
        except InvalidOrder:
            raise CartNotReady(CART_CHANGED) from None
        if order.total_minor <= 0:
            await orders.cancel_order(order.id)
            raise CartNotReady("There is nothing to pay for.")
        return order


def _check_fee_rate(target: CheckoutTarget) -> None:
    """A fee rate outside 0..10000 is a data error: refuse before anything is written."""
    rate = target.platform_fee_bps
    if isinstance(rate, bool) or not 0 <= rate <= MAX_FEE_BPS:
        logger.error(
            "platform_fee_bps out of range; checkout refused",
            extra={"store_id": target.store_id},
        )
        raise CheckoutUnavailable


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
    customer_email: str | None = None


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
    details = obj.get("customer_details")
    email = clean_customer_email(
        details.get("email") if isinstance(details, Mapping) else None
    )
    return _PaidSession(session_id, order_id, intent, amount, currency.upper(), email)


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
        logger.error("paid checkout session without usable fields")
        report_exception(UnappliedCheckoutPayment("unusable"))
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
        report_exception(UnappliedCheckoutPayment(outcome.value))
    else:
        logger.info(
            "checkout payment confirmed: %s",
            outcome.value,
            extra={"order_id": paid.order_id},
        )
    return outcome


def checkout_payment_handler(
    open_store: Callable[[str], AbstractAsyncContextManager[AsyncSession]],
    emails: OrderEmailEnqueuer,
) -> StoreEventHandler:
    """The Connect webhook handler for ``PAYMENT_EVENT_TYPES``.

    Runs inside the platform claim's transaction and commits only the store session it opens:
    the write is idempotent (``mark_checkout_paid``), so Stripe's retry after a failed claim
    changes nothing.

    Order emails (KAN-81): the payment that moves the order to ``paid`` also writes the
    shopper's address and the confirmation and new-order alert rows, in the same store
    transaction. After the commit, every one of those rows still ``pending`` is published to
    QStash, on this delivery and on any redelivery that finds the order already paid. A
    publish failure raises, so the webhook answers 500 and Stripe delivers again.
    """

    async def handle(route: ConnectRoute, obj: Mapping[str, Any]) -> None:
        store_id = route.store_id
        if store_id is None:  # routing always sets one for store-scoped events
            logger.error("checkout payment event routed without a store")
            report_exception(UnappliedCheckoutPayment("no store"))
            return
        paid = _paid_session(obj)
        async with open_store(store_id) as session:
            outcome = await confirm_checkout_payment(session, obj)
            if outcome is PaymentOutcome.PAID and paid is not None:
                await record_order_emails(
                    session,
                    store_id=store_id,
                    order_id=paid.order_id,
                    kinds=PAID_KINDS,
                    customer_email=paid.customer_email,
                )
            await session.commit()
            jobs = (
                await pending_jobs(
                    session, store_id=store_id, order_id=paid.order_id, kinds=PAID_KINDS
                )
                if paid is not None
                and outcome in (PaymentOutcome.PAID, PaymentOutcome.ALREADY_PAID)
                else []
            )
        await publish_jobs(emails, jobs)

    return handle
