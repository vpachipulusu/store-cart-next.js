"""Orders in a store database: purchase snapshots and the status flow (KAN-78). No FastAPI imports.

Every function takes the ``AsyncSession`` of one store (from the store session factory in ``store_sessions``, the only
door to a store database) and never commits: the caller owns the transaction. There is no
ORM model for store tables; the SQL is explicit and every value is a bound parameter.

* ``create_order`` copies the product name, SKU, variant label and unit price from the
  catalogue into the order lines and computes the tax once, so later catalogue edits never
  change an order. The tax rate is an input (basis points) because no store tax setting
  exists yet. Stock is not touched here.
* ``transition_order`` moves an order along ``ALLOWED_TRANSITIONS`` with one conditional
  ``UPDATE``, so two concurrent moves cannot both succeed from the same status.
* ``fulfil_order`` is the only way to reach ``fulfilled``: it stores the tracking number,
  the optional carrier and ``fulfilled_at`` in the same conditional ``UPDATE`` (KAN-79).
* Checkout (KAN-68) prices its orders with the store settings in ``store_checkout`` and
  writes them with ``insert_order``; ``link_checkout_session`` and ``mark_checkout_paid``
  tie an order to its Stripe Checkout Session and confirm it at most once.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id

CURRENCY_LENGTH = 3
MAX_LINES = 100
MAX_QUANTITY = 10_000
MAX_TAX_RATE_BPS = 100_000
BPS_DENOMINATOR = 10_000
MAX_MINOR = 2**63 - 1  # the bigint columns
MAX_ID_LENGTH = 100
MAX_LABEL_LENGTH = 255  # order_items.variant_label
MAX_TRACKING_LENGTH = 100  # orders.tracking_number and orders.carrier
SELLABLE_PRODUCT_STATUS = "active"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


# pending > paid > fulfilled; pending/paid > cancelled; paid/fulfilled > refunded.
# Cancelled and refunded are final; nothing moves backwards.
ALLOWED_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = MappingProxyType(
    {
        OrderStatus.PENDING: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
        OrderStatus.PAID: frozenset(
            {OrderStatus.FULFILLED, OrderStatus.CANCELLED, OrderStatus.REFUNDED}
        ),
        OrderStatus.FULFILLED: frozenset({OrderStatus.REFUNDED}),
        OrderStatus.CANCELLED: frozenset(),
        OrderStatus.REFUNDED: frozenset(),
    }
)


class OrderError(Exception):
    """Base class of order service errors."""


class InvalidOrder(OrderError):
    """The order input is not acceptable (message is safe to show)."""


class OrderNotFound(OrderError):
    """No order has this id in this store."""


class InvalidOrderTransition(OrderError):
    def __init__(self, current: OrderStatus, target: OrderStatus) -> None:
        super().__init__(f"An order cannot move from {current.value} to {target.value}")
        self.current = current
        self.target = target


@dataclass(frozen=True)
class OrderLineInput:
    variant_id: str
    quantity: int


@dataclass(frozen=True)
class OrderItemRecord:
    id: str
    product_id: str | None  # null once the product is deleted from the catalogue
    variant_id: str | None
    product_name: str
    sku: str
    variant_label: str | None
    unit_price_minor: int
    quantity: int
    tax_rate_bps: int
    tax_minor: int


@dataclass(frozen=True)
class OrderRecord:
    id: str
    status: OrderStatus
    currency: str
    subtotal_minor: int
    tax_minor: int
    total_minor: int
    items: tuple[OrderItemRecord, ...]
    shipping_minor: int = 0
    prices_include_tax: bool = False


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    """Whether the status flow allows moving from ``current`` to ``target``."""
    return target in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: OrderStatus, target: OrderStatus) -> None:
    """Raise ``InvalidOrderTransition`` unless the move is allowed."""
    if not can_transition(current, target):
        raise InvalidOrderTransition(current, target)


def line_tax_minor(unit_price_minor: int, quantity: int, tax_rate_bps: int) -> int:
    """Tax of one line in minor units, rounded half up (integer arithmetic only)."""
    return (
        unit_price_minor * quantity * tax_rate_bps + BPS_DENOMINATOR // 2
    ) // BPS_DENOMINATOR


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_order_input(
    currency: str, tax_rate_bps: int, lines: Sequence[OrderLineInput]
) -> None:
    if not isinstance(currency, str) or len(currency) != CURRENCY_LENGTH:
        raise InvalidOrder("Currency must be a three-letter upper-case code")
    if not (currency.isascii() and currency.isalpha() and currency.isupper()):
        raise InvalidOrder("Currency must be a three-letter upper-case code")
    if not _is_int(tax_rate_bps) or not 0 <= tax_rate_bps <= MAX_TAX_RATE_BPS:
        raise InvalidOrder("Tax rate is out of range")
    if not 1 <= len(lines) <= MAX_LINES:
        raise InvalidOrder(f"An order needs 1 to {MAX_LINES} lines")
    for line in lines:
        if (
            not isinstance(line.variant_id, str)
            or not 1 <= len(line.variant_id) <= MAX_ID_LENGTH
            or "\0" in line.variant_id
        ):
            raise InvalidOrder("An item is not available")
        if not _is_int(line.quantity) or not 1 <= line.quantity <= MAX_QUANTITY:
            raise InvalidOrder(f"Quantity must be between 1 and {MAX_QUANTITY}")
    if len({line.variant_id for line in lines}) != len(lines):
        raise InvalidOrder("A variant may appear on one line only")


_CATALOGUE_SQL = text(
    """
    SELECT v.id AS variant_id, v.sku, v.price_minor, p.id AS product_id,
           p.title AS product_name, p.status AS product_status,
           (SELECT left(string_agg(pov.value, ' / ' ORDER BY po.position, po.id), :max_label)
              FROM variant_option_values vov
              JOIN product_options po ON po.id = vov.option_id
              JOIN product_option_values pov ON pov.id = vov.option_value_id
             WHERE vov.variant_id = v.id) AS variant_label
      FROM variants v JOIN products p ON p.id = v.product_id
     WHERE v.id = ANY(CAST(:ids AS varchar[]))
     ORDER BY v.id
       FOR SHARE OF v, p
    """
)
_INSERT_ORDER_SQL = text(
    "INSERT INTO orders (id, currency, subtotal_minor, shipping_minor, tax_minor,"
    " total_minor, prices_include_tax, cart_id, checkout_fingerprint,"
    " checkout_expires_at) "
    "VALUES (:id, :currency, :subtotal, :shipping, :tax, :total, :included, :cart_id,"
    " :fingerprint, :expires_at)"
)
_INSERT_ITEM_SQL = text(
    "INSERT INTO order_items (id, order_id, product_id, variant_id, product_name, sku,"
    " variant_label, unit_price_minor, quantity, tax_rate_bps, tax_minor) "
    "VALUES (:id, :order_id, :product_id, :variant_id, :product_name, :sku,"
    " :variant_label, :unit_price, :quantity, :tax_rate_bps, :tax)"
)


async def load_catalogue(
    session: AsyncSession, lines: Sequence[OrderLineInput]
) -> dict[str, RowMapping]:
    """Read the sold variants and share-lock them until the caller's transaction ends.

    The lock keeps a concurrent price edit, unpublish or delete from landing between this
    read and the item inserts, so the snapshot is what the order was priced from.
    """
    ids = [line.variant_id for line in lines]
    rows = (
        (
            await session.execute(
                _CATALOGUE_SQL, {"ids": ids, "max_label": MAX_LABEL_LENGTH}
            )
        )
        .mappings()
        .all()
    )
    found = {row["variant_id"]: row for row in rows}
    for variant_id in ids:
        row = found.get(variant_id)
        if row is None or row["product_status"] != SELLABLE_PRODUCT_STATUS:
            # One message for "missing" and "not for sale": it reveals nothing about drafts.
            raise InvalidOrder("An item is not available")
    return found


async def create_order(
    session: AsyncSession,
    *,
    currency: str,
    tax_rate_bps: int,
    lines: Sequence[OrderLineInput],
) -> OrderRecord:
    """Create a ``pending`` order whose lines snapshot the catalogue as it is now."""
    validate_order_input(currency, tax_rate_bps, lines)
    catalogue = await load_catalogue(session, lines)

    items: list[OrderItemRecord] = []
    for line in lines:
        row = catalogue[line.variant_id]
        items.append(
            OrderItemRecord(
                id=new_id(),
                product_id=row["product_id"],
                variant_id=line.variant_id,
                product_name=row["product_name"],
                sku=row["sku"],
                variant_label=row["variant_label"],
                unit_price_minor=row["price_minor"],
                quantity=line.quantity,
                tax_rate_bps=tax_rate_bps,
                tax_minor=line_tax_minor(
                    row["price_minor"], line.quantity, tax_rate_bps
                ),
            )
        )
    subtotal = sum(item.unit_price_minor * item.quantity for item in items)
    tax = sum(item.tax_minor for item in items)
    if subtotal + tax > MAX_MINOR:
        raise InvalidOrder("The order total is too large")

    order = OrderRecord(
        id=new_id(),
        status=OrderStatus.PENDING,
        currency=currency,
        subtotal_minor=subtotal,
        tax_minor=tax,
        total_minor=subtotal + tax,
        items=tuple(items),
    )
    await insert_order(session, order)
    return order


@dataclass(frozen=True)
class CheckoutOrigin:
    """Where a checkout order came from: the cart, what it was sent for, and when it lapses."""

    cart_id: str
    fingerprint: str
    expires_at: datetime


async def insert_order(
    session: AsyncSession, order: OrderRecord, origin: CheckoutOrigin | None = None
) -> None:
    """Write a priced ``pending`` order and its lines (the caller computed every amount).

    A checkout order carries its ``origin``; with one open order per cart enforced by a
    partial unique index, a second open order for the cart raises ``IntegrityError``.
    """
    await session.execute(
        _INSERT_ORDER_SQL,
        {
            "cart_id": origin.cart_id if origin else None,
            "fingerprint": origin.fingerprint if origin else None,
            "expires_at": origin.expires_at if origin else None,
            "id": order.id,
            "currency": order.currency,
            "subtotal": order.subtotal_minor,
            "shipping": order.shipping_minor,
            "tax": order.tax_minor,
            "total": order.total_minor,
            "included": order.prices_include_tax,
        },
    )
    await session.execute(
        _INSERT_ITEM_SQL,
        [
            {
                "id": item.id,
                "order_id": order.id,
                "product_id": item.product_id,
                "variant_id": item.variant_id,
                "product_name": item.product_name,
                "sku": item.sku,
                "variant_label": item.variant_label,
                "unit_price": item.unit_price_minor,
                "quantity": item.quantity,
                "tax_rate_bps": item.tax_rate_bps,
                "tax": item.tax_minor,
            }
            for item in order.items
        ],
    )


_TRANSITION_SQL = text(
    "UPDATE orders SET status = :target, updated_at = now() "
    "WHERE id = :id AND status = ANY(CAST(:sources AS varchar[])) RETURNING id"
)
_STATUS_SQL = text("SELECT status FROM orders WHERE id = :id")


async def transition_order(
    session: AsyncSession, order_id: str, target: OrderStatus
) -> OrderStatus:
    """Move an order to ``target`` or raise; the status check and the write are one statement."""
    if target is OrderStatus.FULFILLED:
        raise InvalidOrder("Use fulfil_order to fulfil an order")
    sources = sorted(
        status.value for status in OrderStatus if can_transition(status, target)
    )
    moved = (
        await session.execute(
            _TRANSITION_SQL,
            {"id": order_id, "target": target.value, "sources": sources},
        )
    ).first()
    if moved is not None:
        return target
    current = (
        await session.execute(_STATUS_SQL, {"id": order_id})
    ).scalar_one_or_none()
    if current is None:
        raise OrderNotFound(order_id)
    raise InvalidOrderTransition(OrderStatus(current), target)


def clean_tracking_text(value: object, label: str, *, required: bool) -> str | None:
    """Trimmed fulfilment text, 1 to ``MAX_TRACKING_LENGTH`` characters, no control characters."""
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise InvalidOrder(f"{label} is required")
    cleaned = value.strip()
    if not cleaned and not required:
        return None
    if not 1 <= len(cleaned) <= MAX_TRACKING_LENGTH:
        raise InvalidOrder(f"{label} must be 1 to {MAX_TRACKING_LENGTH} characters")
    if not cleaned.isprintable():
        raise InvalidOrder(f"{label} has characters that are not allowed")
    return cleaned


_FULFIL_SQL = text(
    "UPDATE orders SET status = 'fulfilled', tracking_number = :tracking,"
    " carrier = :carrier, fulfilled_at = now(), updated_at = now() "
    "WHERE id = :id AND status = 'paid' RETURNING id"
)


async def fulfil_order(
    session: AsyncSession,
    order_id: str,
    tracking_number: str,
    carrier: str | None = None,
) -> None:
    """Move a ``paid`` order to ``fulfilled`` and record how it was shipped, in one statement."""
    tracking = clean_tracking_text(tracking_number, "Tracking number", required=True)
    carrier_name = clean_tracking_text(carrier, "Carrier", required=False)
    moved = (
        await session.execute(
            _FULFIL_SQL, {"id": order_id, "tracking": tracking, "carrier": carrier_name}
        )
    ).first()
    if moved is not None:
        return
    current = (
        await session.execute(_STATUS_SQL, {"id": order_id})
    ).scalar_one_or_none()
    if current is None:
        raise OrderNotFound(order_id)
    raise InvalidOrderTransition(OrderStatus(current), OrderStatus.FULFILLED)


class PaymentOutcome(StrEnum):
    PAID = "paid"  # this call moved the order to paid
    ALREADY_PAID = "already_paid"  # an earlier delivery did; nothing changed
    MISMATCH = "mismatch"  # the session does not match the order; nothing changed
    NOT_FOUND = "not_found"


_LINK_SESSION_SQL = text(
    "UPDATE orders SET stripe_checkout_session_id = :session_id,"
    " stripe_checkout_url = :url, updated_at = now() "
    "WHERE id = :id AND status = 'pending'"
    " AND stripe_checkout_session_id IS NULL RETURNING id"
)
_SESSION_OWNER_SQL = text(
    "SELECT id FROM orders WHERE stripe_checkout_session_id = :session_id"
)
_MARK_PAID_SQL = text(
    "UPDATE orders SET status = 'paid', paid_at = now(), updated_at = now(),"
    " stripe_checkout_session_id = :session_id,"
    " stripe_payment_intent_id = :payment_intent_id "
    "WHERE id = :id AND status = 'pending'"
    " AND (stripe_checkout_session_id IS NULL"
    " OR stripe_checkout_session_id = :session_id)"
    " AND total_minor = :amount AND currency = :currency "
    "RETURNING id"
)
_PAYMENT_STATE_SQL = text(
    "SELECT paid_at, stripe_checkout_session_id FROM orders WHERE id = :id"
)


async def link_checkout_session(
    session: AsyncSession, order_id: str, session_id: str, url: str | None = None
) -> bool:
    """Record the Checkout Session (and its page) of a pending order; false if it is not
    pending or already has a session."""
    linked = (
        await session.execute(
            _LINK_SESSION_SQL, {"id": order_id, "session_id": session_id, "url": url}
        )
    ).first()
    return linked is not None


async def mark_checkout_paid(
    session: AsyncSession,
    *,
    order_id: str,
    session_id: str,
    payment_intent_id: str | None,
    amount_minor: int,
    currency: str,
) -> PaymentOutcome:
    """Move a ``pending`` order to ``paid`` for its Checkout Session, at most once.

    One conditional ``UPDATE``: the order must still be pending, be linked to this session
    (or to none yet, when the webhook beats the link), and charge exactly its total in its
    currency. A rerun, or a concurrent delivery that waited on the row lock, finds the order
    paid and changes nothing. A session already linked to another order never pays this one
    (and the unique index on the column stops two orders sharing one).
    """
    owner = (
        await session.execute(_SESSION_OWNER_SQL, {"session_id": session_id})
    ).scalar_one_or_none()
    if owner is not None and owner != order_id:
        return PaymentOutcome.MISMATCH
    moved = (
        await session.execute(
            _MARK_PAID_SQL,
            {
                "id": order_id,
                "session_id": session_id,
                "payment_intent_id": payment_intent_id,
                "amount": amount_minor,
                "currency": currency,
            },
        )
    ).first()
    if moved is not None:
        return PaymentOutcome.PAID
    state = (
        (await session.execute(_PAYMENT_STATE_SQL, {"id": order_id}))
        .mappings()
        .one_or_none()
    )
    if state is None:
        return PaymentOutcome.NOT_FOUND
    # Paid by this session before (a cancelled order with this session is a mismatch).
    if (
        state["paid_at"] is not None
        and state["stripe_checkout_session_id"] == session_id
    ):
        return PaymentOutcome.ALREADY_PAID
    return PaymentOutcome.MISMATCH


@dataclass(frozen=True)
class OpenCheckout:
    """The pending checkout order of a cart, as far as its session is known."""

    order_id: str
    fingerprint: str | None
    session_id: str | None
    url: str | None
    expires_at: datetime | None


_OPEN_CHECKOUT_SQL = text(
    "SELECT id, checkout_fingerprint, stripe_checkout_session_id,"
    " stripe_checkout_url, checkout_expires_at FROM orders "
    "WHERE cart_id = :cart_id AND status = 'pending'"
)
_ORDER_SQL = text(
    "SELECT id, status, currency, subtotal_minor, shipping_minor, tax_minor,"
    " total_minor, prices_include_tax FROM orders WHERE id = :id"
)
_ORDER_ITEMS_SQL = text(
    "SELECT id, product_id, variant_id, product_name, sku, variant_label,"
    " unit_price_minor, quantity, tax_rate_bps, tax_minor "
    "FROM order_items WHERE order_id = :id ORDER BY id"
)
_CANCEL_PENDING_SQL = text(
    "UPDATE orders SET status = 'cancelled', updated_at = now() "
    "WHERE id = :id AND status = 'pending' RETURNING id"
)


async def find_open_checkout(
    session: AsyncSession, cart_id: str
) -> OpenCheckout | None:
    """The cart's pending order, if any (the unique index allows at most one)."""
    row = (
        (await session.execute(_OPEN_CHECKOUT_SQL, {"cart_id": cart_id}))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return OpenCheckout(
        order_id=row["id"],
        fingerprint=row["checkout_fingerprint"],
        session_id=row["stripe_checkout_session_id"],
        url=row["stripe_checkout_url"],
        expires_at=row["checkout_expires_at"],
    )


async def load_order(session: AsyncSession, order_id: str) -> OrderRecord:
    """An order with its lines, as it was priced. Raises ``OrderNotFound``."""
    row = (await session.execute(_ORDER_SQL, {"id": order_id})).mappings().first()
    if row is None:
        raise OrderNotFound(order_id)
    items = (await session.execute(_ORDER_ITEMS_SQL, {"id": order_id})).mappings().all()
    return OrderRecord(
        id=row["id"],
        status=OrderStatus(row["status"]),
        currency=row["currency"],
        subtotal_minor=row["subtotal_minor"],
        tax_minor=row["tax_minor"],
        total_minor=row["total_minor"],
        items=tuple(OrderItemRecord(**dict(item)) for item in items),
        shipping_minor=row["shipping_minor"],
        prices_include_tax=row["prices_include_tax"],
    )


async def cancel_pending_order(session: AsyncSession, order_id: str) -> bool:
    """Cancel an order that is still ``pending``; false when it already moved. Does not commit."""
    moved = (await session.execute(_CANCEL_PENDING_SQL, {"id": order_id})).first()
    return moved is not None
