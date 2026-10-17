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
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
MAX_LABEL_LENGTH = 255  # order_items.variant_label
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


def _validate(
    currency: str, tax_rate_bps: int, lines: Sequence[OrderLineInput]
) -> None:
    if len(currency) != CURRENCY_LENGTH or not (
        currency.isascii() and currency.isalpha() and currency.isupper()
    ):
        raise InvalidOrder("Currency must be a three-letter upper-case code")
    if not 0 <= tax_rate_bps <= MAX_TAX_RATE_BPS:
        raise InvalidOrder("Tax rate is out of range")
    if not 1 <= len(lines) <= MAX_LINES:
        raise InvalidOrder(f"An order needs 1 to {MAX_LINES} lines")
    if len({line.variant_id for line in lines}) != len(lines):
        raise InvalidOrder("A variant may appear on one line only")
    if any(not 1 <= line.quantity <= MAX_QUANTITY for line in lines):
        raise InvalidOrder(f"Quantity must be between 1 and {MAX_QUANTITY}")


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
    "INSERT INTO orders (id, currency, subtotal_minor, tax_minor, total_minor) "
    "VALUES (:id, :currency, :subtotal, :tax, :total)"
)
_INSERT_ITEM_SQL = text(
    "INSERT INTO order_items (id, order_id, product_id, variant_id, product_name, sku,"
    " variant_label, unit_price_minor, quantity, tax_rate_bps, tax_minor) "
    "VALUES (:id, :order_id, :product_id, :variant_id, :product_name, :sku,"
    " :variant_label, :unit_price, :quantity, :tax_rate_bps, :tax)"
)


async def _load_catalogue(
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
    _validate(currency, tax_rate_bps, lines)
    catalogue = await _load_catalogue(session, lines)

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
    await session.execute(
        _INSERT_ORDER_SQL,
        {
            "id": order.id,
            "currency": currency,
            "subtotal": subtotal,
            "tax": tax,
            "total": order.total_minor,
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
            for item in items
        ],
    )
    return order


_TRANSITION_SQL = text(
    "UPDATE orders SET status = :target, updated_at = now() "
    "WHERE id = :id AND status = ANY(CAST(:sources AS varchar[])) RETURNING id"
)
_STATUS_SQL = text("SELECT status FROM orders WHERE id = :id")


async def transition_order(
    session: AsyncSession, order_id: str, target: OrderStatus
) -> OrderStatus:
    """Move an order to ``target`` or raise; the status check and the write are one statement."""
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
