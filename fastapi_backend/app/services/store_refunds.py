"""Refunds of paid orders in a store database (KAN-80). No FastAPI imports, never commits.

A refund is a row in ``order_refunds`` with the lines it covers (``order_refund_items``). It
moves ``pending`` > ``succeeded`` or ``failed``, exactly once:

* ``reserve_refund`` locks the order row, checks what can still be refunded and inserts a
  ``pending`` refund. Pending and succeeded refunds both count against the order (what is
  left is the order total, or the line quantities, minus them), so two concurrent requests
  cannot refund the same units or money twice. The caller commits, then asks Stripe.
* ``settle_refund`` applies Stripe's answer. One conditional ``UPDATE ... WHERE status =
  'pending'`` decides the winner, under the order's row lock, so a replayed or concurrent
  settlement (the API response and the webhook race) changes nothing the second time. A
  ``failed`` refund frees what it held. A ``succeeded`` one restocks, when the merchant asked
  for it, in the same transaction, and moves the order to ``refunded`` once the succeeded
  refunds add up to its total.

Restock (merchant toggle per refund, default off) returns only what the order took: at most
``order_items.stock_taken`` minus what earlier refunds already returned, so an oversold line
(never taken) adds nothing, a partial refund returns only its quantities, and stock can never
rise above what the order took out. A line whose variant was deleted is skipped.

Amounts: a line's share of a partial refund is ``unit_price * q`` plus, when prices exclude
tax, ``tax * q // quantity`` taken cumulatively, so the parts of a line add up to the line to
the minor unit. Shipping is refunded only by a full (remaining) refund.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.sentry import report_exception
from app.repositories.connect_events import ConnectRoute
from app.services.store_orders import (
    MAX_LINES,
    MAX_QUANTITY,
    InvalidOrder,
    InvalidOrderTransition,
    OrderError,
    OrderNotFound,
    OrderStatus,
    transition_order,
)
from app.services.stripe_connect import StoreEventHandler

logger = logging.getLogger(__name__)

REFUNDABLE_STATUSES = frozenset({OrderStatus.PAID.value, OrderStatus.FULFILLED.value})
MAX_ID_TEXT_LENGTH = 100


class RefundNotAllowed(OrderError):
    """The order cannot be refunded as asked (HTTP 409; the message is safe to show)."""


class UnappliedRefundEvent(Exception):
    """A refund event that matched no refund of ours (Sentry only)."""


class RefundOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class RefundLineInput:
    order_item_id: str
    quantity: int


@dataclass(frozen=True)
class RefundPlan:
    """A reserved (``pending``) refund: what to ask Stripe for."""

    id: str
    order_id: str
    amount_minor: int
    currency: str
    payment_intent_id: str
    restock: bool
    replayed: bool = False  # the caller's Idempotency-Key found this refund already


_LOCK_ORDER_SQL = text(
    "SELECT status, currency, total_minor, stripe_payment_intent_id, prices_include_tax "
    "FROM orders WHERE id = :id FOR UPDATE"
)
_ITEMS_SQL = text(
    "SELECT id, quantity, unit_price_minor, tax_minor FROM order_items "
    "WHERE order_id = :id ORDER BY id"
)
_HELD_QUANTITY_SQL = text(
    "SELECT ri.order_item_id, CAST(sum(ri.quantity) AS integer) AS held "
    "FROM order_refund_items ri JOIN order_refunds r ON r.id = ri.refund_id "
    "WHERE r.order_id = :id AND r.status <> 'failed' GROUP BY ri.order_item_id"
)
_HELD_AMOUNT_SQL = text(
    "SELECT CAST(COALESCE(sum(amount_minor), 0) AS bigint) FROM order_refunds "
    "WHERE order_id = :id AND status <> 'failed'"
)
_INSERT_REFUND_SQL = text(
    "INSERT INTO order_refunds (id, order_id, amount_minor, currency, restock, client_key) "
    "VALUES (:id, :order_id, :amount, :currency, :restock, :client_key)"
)
_INSERT_REFUND_ITEM_SQL = text(
    "INSERT INTO order_refund_items (refund_id, order_item_id, quantity) "
    "VALUES (:refund_id, :order_item_id, :quantity)"
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _line_gross(
    unit_price_minor: int,
    tax_minor: int,
    quantity: int,
    line_quantity: int,
    *,
    included: bool,
) -> int:
    """What the first ``quantity`` units of a line cost the shopper (cumulative share)."""
    tax = 0 if included else tax_minor * quantity // line_quantity
    return unit_price_minor * quantity + tax


def _validate_lines(lines: Sequence[RefundLineInput]) -> None:
    if not 1 <= len(lines) <= MAX_LINES:
        raise InvalidOrder(f"A refund needs 1 to {MAX_LINES} lines")
    seen: set[str] = set()
    for line in lines:
        if (
            not isinstance(line.order_item_id, str)
            or not 1 <= len(line.order_item_id) <= MAX_ID_TEXT_LENGTH
            or "\0" in line.order_item_id
        ):
            raise InvalidOrder("An item is not part of this order")
        if not _is_int(line.quantity) or not 1 <= line.quantity <= MAX_QUANTITY:
            raise InvalidOrder(f"Quantity must be between 1 and {MAX_QUANTITY}")
        if line.order_item_id in seen:
            raise InvalidOrder("An item may appear on one line only")
        seen.add(line.order_item_id)


async def reserve_refund(
    session: AsyncSession,
    order_id: str,
    lines: Sequence[RefundLineInput] | None,
    *,
    restock: bool = False,
    client_key: str | None = None,
) -> RefundPlan:
    """Insert a ``pending`` refund of ``lines`` (None: everything that remains). Does not commit.

    With a ``client_key`` (the caller's ``Idempotency-Key``), a refund already made under that key
    on this order is returned (``replayed``) and nothing is inserted, whatever the order's
    status is by now.

    Raises ``OrderNotFound``, ``InvalidOrder`` (bad lines) or ``RefundNotAllowed`` (not paid,
    no payment to refund, or more than remains).
    """
    if lines is not None:
        _validate_lines(lines)
    order = (
        (await session.execute(_LOCK_ORDER_SQL, {"id": order_id}))
        .mappings()
        .one_or_none()
    )
    if order is None:
        raise OrderNotFound(order_id)
    payment_intent = order["stripe_payment_intent_id"]
    if client_key is not None:
        replay = await _replayed(session, order_id, client_key, lines, payment_intent)
        if replay is not None:
            return replay
    if order["status"] not in REFUNDABLE_STATUSES:
        raise RefundNotAllowed("Only a paid order can be refunded")
    if payment_intent is None:
        raise RefundNotAllowed("This order has no payment to refund")

    items = {
        row["id"]: row
        for row in (await session.execute(_ITEMS_SQL, {"id": order_id})).mappings()
    }
    held = {
        row["order_item_id"]: row["held"]
        for row in (
            await session.execute(_HELD_QUANTITY_SQL, {"id": order_id})
        ).mappings()
    }
    held_amount = (
        await session.execute(_HELD_AMOUNT_SQL, {"id": order_id})
    ).scalar_one()
    included: bool = order["prices_include_tax"]

    chosen: list[tuple[str, int]] = []
    if lines is None:
        for item_id, item in items.items():
            remaining = item["quantity"] - held.get(item_id, 0)
            if remaining > 0:
                chosen.append((item_id, remaining))
        amount = order["total_minor"] - held_amount
    else:
        amount = 0
        for line in lines:
            target = items.get(line.order_item_id)
            if target is None:
                raise InvalidOrder("An item is not part of this order")
            already = held.get(line.order_item_id, 0)
            if line.quantity > target["quantity"] - already:
                raise RefundNotAllowed("More than remains of an item was requested")
            chosen.append((line.order_item_id, line.quantity))
            args = (target["unit_price_minor"], target["tax_minor"])
            amount += _line_gross(
                *args, already + line.quantity, target["quantity"], included=included
            ) - _line_gross(*args, already, target["quantity"], included=included)

    if amount <= 0 or held_amount + amount > order["total_minor"]:
        raise RefundNotAllowed("There is nothing left to refund")

    refund_id = new_id()
    await session.execute(
        _INSERT_REFUND_SQL,
        {
            "id": refund_id,
            "order_id": order_id,
            "amount": amount,
            "currency": order["currency"],
            "restock": restock,
            "client_key": client_key,
        },
    )
    if chosen:
        await session.execute(
            _INSERT_REFUND_ITEM_SQL,
            [
                {"refund_id": refund_id, "order_item_id": item_id, "quantity": quantity}
                for item_id, quantity in chosen
            ],
        )
    return RefundPlan(
        id=refund_id,
        order_id=order_id,
        amount_minor=amount,
        currency=order["currency"],
        payment_intent_id=payment_intent,
        restock=restock,
    )


_BY_KEY_SQL = text(
    "SELECT id, amount_minor, currency, restock FROM order_refunds "
    "WHERE order_id = :order_id AND client_key = :key"
)
_REFUND_LINES_SQL = text(
    "SELECT order_item_id, quantity FROM order_refund_items WHERE refund_id = :id"
)
_UNSENT_SQL = text(
    "SELECT r.id, r.order_id, r.amount_minor, r.currency, r.restock,"
    " o.stripe_payment_intent_id "
    "FROM order_refunds r JOIN orders o ON o.id = r.order_id "
    "WHERE r.order_id = :order_id AND r.status = 'pending'"
    " AND r.stripe_refund_id IS NULL"
    " AND r.created_at <= now() - make_interval(secs => :grace) "
    "ORDER BY r.created_at, r.id"
)


async def _replayed(
    session: AsyncSession,
    order_id: str,
    client_key: str,
    lines: Sequence[RefundLineInput] | None,
    payment_intent: str | None,
) -> RefundPlan | None:
    """The refund this order already made under ``client_key``, if any (checked under the lock)."""
    row = (
        (await session.execute(_BY_KEY_SQL, {"order_id": order_id, "key": client_key}))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if lines is not None:
        stored = {
            r["order_item_id"]: r["quantity"]
            for r in (
                await session.execute(_REFUND_LINES_SQL, {"id": row["id"]})
            ).mappings()
        }
        if stored != {line.order_item_id: line.quantity for line in lines}:
            raise RefundNotAllowed(
                "This Idempotency-Key was used for a different refund"
            )
    return RefundPlan(
        id=row["id"],
        order_id=order_id,
        amount_minor=row["amount_minor"],
        currency=row["currency"],
        payment_intent_id=payment_intent or "",
        restock=row["restock"],
        replayed=True,
    )


async def unsent_refunds(
    session: AsyncSession, order_id: str, grace_seconds: float
) -> list[RefundPlan]:
    """Pending refunds of the order Stripe has never confirmed, older than ``grace_seconds``.

    Their request may never have reached Stripe (timeout, crash after the reservation). Asking
    Stripe again with the same idempotency key (the refund id) is safe: it either creates the
    refund or returns the one it made. The grace keeps this off requests still in flight.
    """
    rows = (
        (
            await session.execute(
                _UNSENT_SQL, {"order_id": order_id, "grace": grace_seconds}
            )
        )
        .mappings()
        .all()
    )
    return [
        RefundPlan(
            id=row["id"],
            order_id=row["order_id"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            payment_intent_id=row["stripe_payment_intent_id"],
            restock=row["restock"],
        )
        for row in rows
        if row["stripe_payment_intent_id"] is not None
    ]


_REFUND_ORDER_SQL = text("SELECT order_id FROM order_refunds WHERE id = :id")
_LOCK_ORDER_ROW_SQL = text("SELECT id FROM orders WHERE id = :id FOR UPDATE")
_SETTLE_SQL = text(
    "UPDATE order_refunds SET status = :status,"
    " stripe_refund_id = COALESCE(:stripe_refund_id, stripe_refund_id),"
    " updated_at = now() "
    "WHERE id = :id AND status = 'pending' RETURNING restock"
)
_RECORD_STRIPE_ID_SQL = text(
    "UPDATE order_refunds SET stripe_refund_id = :stripe_refund_id, updated_at = now() "
    "WHERE id = :id AND status = 'pending' AND stripe_refund_id IS NULL RETURNING id"
)
_RESTOCK_LINES_SQL = text(
    "SELECT i.id, i.variant_id, ri.quantity AS refunded,"
    " i.stock_taken - i.restocked_quantity AS returnable "
    "FROM order_refund_items ri JOIN order_items i ON i.id = ri.order_item_id "
    "WHERE ri.refund_id = :id ORDER BY i.variant_id NULLS LAST, i.id"
)
_RESTOCK_VARIANT_SQL = text(
    "UPDATE variants SET stock = stock + :quantity, updated_at = now() "
    "WHERE id = :variant_id RETURNING id"
)
_MARK_RESTOCKED_ITEM_SQL = text(
    "UPDATE order_items SET restocked_quantity = restocked_quantity + :quantity "
    "WHERE id = :id"
)
_MARK_RESTOCKED_SQL = text(
    "UPDATE order_refunds SET restocked_at = now() WHERE id = :id"
)
_SUCCEEDED_AMOUNT_SQL = text(
    "SELECT CAST(COALESCE(sum(amount_minor), 0) AS bigint) FROM order_refunds "
    "WHERE order_id = :id AND status = 'succeeded'"
)
_ORDER_TOTAL_SQL = text("SELECT total_minor FROM orders WHERE id = :id")


async def record_stripe_refund(
    session: AsyncSession, refund_id: str, stripe_refund_id: str
) -> bool:
    """Remember Stripe's id for a still-pending refund; false when it is settled or has one."""
    recorded = (
        await session.execute(
            _RECORD_STRIPE_ID_SQL,
            {"id": refund_id, "stripe_refund_id": stripe_refund_id},
        )
    ).first()
    return recorded is not None


async def settle_refund(
    session: AsyncSession,
    refund_id: str,
    outcome: RefundOutcome,
    *,
    stripe_refund_id: str | None = None,
) -> bool:
    """Apply Stripe's answer to a pending refund, at most once. Does not commit.

    True when this call settled it; false when it was already settled (or unknown), in which
    case nothing changed. Every settlement of an order runs under that order's row lock, so
    the check "do the succeeded refunds cover the total" cannot miss a concurrent one.
    """
    order_id = (
        await session.execute(_REFUND_ORDER_SQL, {"id": refund_id})
    ).scalar_one_or_none()
    if order_id is None:
        return False
    await session.execute(_LOCK_ORDER_ROW_SQL, {"id": order_id})
    settled = (
        await session.execute(
            _SETTLE_SQL,
            {
                "id": refund_id,
                "status": outcome.value,
                "stripe_refund_id": stripe_refund_id,
            },
        )
    ).first()
    if settled is None:
        return False
    if outcome is not RefundOutcome.SUCCEEDED:
        return True
    if settled.restock:
        await _restock(session, refund_id)
    await _complete_order_if_refunded(session, order_id)
    return True


async def _restock(session: AsyncSession, refund_id: str) -> None:
    """Return the refund's units to stock, never more than the order took. Runs once.

    ``restocked_at`` is set only when some unit was returned.
    """
    returned_any = False
    lines = (
        (await session.execute(_RESTOCK_LINES_SQL, {"id": refund_id})).mappings().all()
    )
    for line in lines:
        quantity = min(line["refunded"], line["returnable"])
        if quantity <= 0 or line["variant_id"] is None:  # never taken, or variant gone
            continue
        returned = (
            await session.execute(
                _RESTOCK_VARIANT_SQL,
                {"variant_id": line["variant_id"], "quantity": quantity},
            )
        ).first()
        if returned is not None:
            returned_any = True
            await session.execute(
                _MARK_RESTOCKED_ITEM_SQL, {"id": line["id"], "quantity": quantity}
            )
    if returned_any:
        await session.execute(_MARK_RESTOCKED_SQL, {"id": refund_id})


async def _complete_order_if_refunded(session: AsyncSession, order_id: str) -> None:
    refunded = (
        await session.execute(_SUCCEEDED_AMOUNT_SQL, {"id": order_id})
    ).scalar_one()
    total = (await session.execute(_ORDER_TOTAL_SQL, {"id": order_id})).scalar_one()
    if refunded < total:
        return
    try:
        await transition_order(session, order_id, OrderStatus.REFUNDED)
    except InvalidOrderTransition:
        logger.warning("fully refunded order could not move to refunded")


# --- Stripe refund events ----------------------------------------------------------------

REFUND_EVENT_TYPES = ("refund.created", "refund.updated", "refund.failed")
_STRIPE_OUTCOMES: Mapping[str, RefundOutcome] = {
    "succeeded": RefundOutcome.SUCCEEDED,
    "failed": RefundOutcome.FAILED,
    "canceled": RefundOutcome.FAILED,
}
_REFUND_ROW_SQL = text(
    "SELECT r.order_id, r.amount_minor, r.currency, r.stripe_refund_id, r.status,"
    " o.stripe_payment_intent_id "
    "FROM order_refunds r JOIN orders o ON o.id = r.order_id WHERE r.id = :id"
)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _metadata_text(obj: Mapping[str, Any], key: str) -> str | None:
    metadata = obj.get("metadata")
    value = _text(metadata.get(key)) if isinstance(metadata, Mapping) else None
    if value is None or len(value) > MAX_ID_TEXT_LENGTH:
        return None
    return value


async def apply_refund_event(
    session: AsyncSession, obj: Mapping[str, Any]
) -> bool | None:
    """Settle the refund a Stripe ``refund`` object belongs to. Does not commit.

    The refund is found by the ``refund_id`` we put in its metadata and must agree with our
    row (order, amount, currency, payment and Stripe refund id), or nothing changes and the
    event is reported. None when there is nothing to settle (a refund still pending at
    Stripe, which only has its id recorded) or the event is not ours; otherwise whether this
    call settled the refund.
    """
    stripe_id = _text(obj.get("id"))
    refund_id = _metadata_text(obj, "refund_id")
    if stripe_id is None or refund_id is None:
        logger.info("refund event without our metadata: not applied")
        return None
    row = (
        (await session.execute(_REFUND_ROW_SQL, {"id": refund_id}))
        .mappings()
        .one_or_none()
    )
    amount, currency = obj.get("amount"), _text(obj.get("currency"))
    payment_intent = _text(obj.get("payment_intent"))
    if (
        row is None
        or _metadata_text(obj, "order_id") != row["order_id"]
        or not _is_int(amount)
        or amount != row["amount_minor"]
        or currency is None
        or currency.upper() != row["currency"]
        or payment_intent != row["stripe_payment_intent_id"]
        or row["stripe_refund_id"] not in (None, stripe_id)
    ):
        logger.error(
            "refund event does not match a refund", extra={"refund_id": refund_id}
        )
        report_exception(UnappliedRefundEvent("mismatch"))
        return None
    outcome = _STRIPE_OUTCOMES.get(str(obj.get("status")))
    try:
        # A savepoint, so a constraint failure leaves the caller's transaction usable.
        async with session.begin_nested():
            if outcome is None:
                await record_stripe_refund(session, refund_id, stripe_id)
                return None
            settled = await settle_refund(
                session, refund_id, outcome, stripe_refund_id=stripe_id
            )
    except IntegrityError:
        # For example a Stripe refund id already recorded on another refund: ack, do not loop.
        logger.error(
            "refund event violates a constraint", extra={"refund_id": refund_id}
        )
        report_exception(UnappliedRefundEvent("integrity"))
        return None
    if not settled and row["status"] not in ("pending", outcome.value):
        # Stripe changed its mind after we settled (a refund failing after it succeeded, or a
        # success for a refund we released): nothing is applied, so a person must look.
        logger.error(
            "refund event contradicts a settled refund",
            extra={"refund_id": refund_id, "stored": row["status"]},
        )
        report_exception(UnappliedRefundEvent("contradicts settled refund"))
    return settled


def refund_event_handler(
    open_store: Callable[[str], AbstractAsyncContextManager[AsyncSession]],
) -> StoreEventHandler:
    """The Connect webhook handler for ``REFUND_EVENT_TYPES``.

    Runs inside the platform claim's transaction and commits only the store session it opens:
    ``settle_refund`` changes a refund once, so Stripe's retry after a failed platform claim
    changes nothing.
    """

    async def handle(route: ConnectRoute, obj: Mapping[str, Any]) -> None:
        if route.store_id is None:  # routing always sets one for store-scoped events
            logger.error("refund event routed without a store")
            report_exception(UnappliedRefundEvent("no store"))
            return
        async with open_store(route.store_id) as session:
            await apply_refund_event(session, obj)
            await session.commit()

    return handle
