"""Expiry of unpaid checkout orders (KAN-256). No FastAPI imports.

A checkout order is ``pending`` until its Stripe Checkout Session is paid. The session is
created with an explicit ``expires_at`` (``SESSION_LIFETIME``, stored on the order as
``checkout_expires_at``), so every unpaid order ends:

* ``checkout.session.expired`` and ``checkout.session.async_payment_failed`` (Connect
  webhook) cancel the order linked to that session while it is still ``pending``. One conditional ``UPDATE``: a redelivery, a paid order and
  an order linked to another session are all left alone.
* The sweep is the backstop for a lost event and for an order that never got a session link:
  it looks at pending orders ``SWEEP_GRACE`` past ``checkout_expires_at``. An order with no
  session id is cancelled. An order with one is cancelled only after Stripe confirms the
  session is expired (``expire_session`` answers ``EXPIRED``): a session the shopper completed
  (a delayed payment method that is still settling, or a webhook that has not arrived) is left
  ``pending`` for its payment event, and so is any order the sweep cannot verify (Stripe
  error, no connected account). Checkout sweeps a few unlinked orders of its own store
  before it starts (no Stripe call on a shopper's request), and
  ``commands.sweep_checkout_orders`` pages through every ACTIVE store and verifies sessions.

No database transaction is held across a Stripe call.
"""

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sentry import report_exception
from app.core.stripe_billing import StripeError
from app.core.stripe_checkout import ExpireOutcome, StripeCheckout
from app.repositories.connect_events import ConnectRoute
from app.services.store_orders import cancel_pending_order
from app.services.stripe_connect import StoreEventHandler

logger = logging.getLogger(__name__)

EXPIRED_EVENT_TYPE = "checkout.session.expired"
# A delayed payment method that failed after the shopper completed the session: the session is
# over and can never be paid, so its order ends like an expired one (otherwise the cart's one
# open order would block every later checkout).
FAILED_EVENT_TYPE = "checkout.session.async_payment_failed"
ENDED_EVENT_TYPES = (EXPIRED_EVENT_TYPE, FAILED_EVENT_TYPE)
# Stripe accepts an expiry from 30 minutes to 24 hours after the session is created. An hour
# leaves a long window in which a start that never learned its session can still be resumed.
SESSION_LIFETIME = timedelta(minutes=60)
# A session is created again for an order (same idempotency key, same ``expires_at``) only
# while Stripe would still accept that expiry (30 minutes ahead, plus a minute of margin).
RESUME_MIN_REMAINING = timedelta(minutes=31)
# An open session closer to its end than this is not handed to the shopper again.
REUSE_MARGIN = timedelta(minutes=5)
SWEEP_GRACE = timedelta(minutes=10)
SWEEP_BATCH = 200
START_SWEEP_BATCH = 5  # unlinked orders a checkout start cancels (no Stripe call)
SESSION_ID_MAX_LENGTH = 255
_BEGINNING = datetime(1970, 1, 1, tzinfo=UTC)

_CANCEL_EXPIRED_SQL = text(
    "UPDATE orders SET status = 'cancelled', updated_at = now() "
    "WHERE stripe_checkout_session_id = :session_id AND status = 'pending' "
    "RETURNING id"
)
_CANDIDATES_SQL = text(
    "SELECT id, stripe_checkout_session_id AS session_id,"
    " checkout_expires_at AS expires_at FROM orders "
    "WHERE status = 'pending' AND checkout_expires_at IS NOT NULL"
    " AND checkout_expires_at < now() - make_interval(secs => :grace)"
    " AND (CAST(:with_sessions AS boolean) OR stripe_checkout_session_id IS NULL)"
    " AND (checkout_expires_at, id) > (CAST(:after_at AS timestamptz), :after_id) "
    "ORDER BY checkout_expires_at, id LIMIT :batch"
)


class UnusableExpiredSession(Exception):
    """A ``checkout.session.expired`` event with no usable session id (Sentry only)."""


@dataclass(frozen=True)
class SweepCursor:
    """Where the next page of the sweep starts (candidates are ordered by expiry, then id)."""

    expires_at: datetime
    order_id: str


@dataclass(frozen=True)
class SweepPage:
    examined: int
    cancelled: int
    cursor: SweepCursor | None  # None when nothing was examined


def _session_id(obj: Mapping[str, Any]) -> str | None:
    value = obj.get("id")
    if isinstance(value, str) and 1 <= len(value) <= SESSION_ID_MAX_LENGTH:
        return value
    return None


async def cancel_expired_session_order(
    session: AsyncSession, obj: Mapping[str, Any]
) -> bool:
    """Cancel the pending order linked to an expired session. Does not commit.

    False when nothing changed: the order is already cancelled or paid, the session is linked
    to no order (an unlinked order is the sweep's), or the event is unusable.
    """
    session_id = _session_id(obj)
    if session_id is None:
        logger.error("expired checkout session without a usable id")
        report_exception(UnusableExpiredSession("no session id"))
        return False
    cancelled = (
        await session.execute(_CANCEL_EXPIRED_SQL, {"session_id": session_id})
    ).first()
    if cancelled is None:
        logger.info("expired checkout session changed no order")
        return False
    logger.info("expired checkout session cancelled its order")
    return True


def checkout_expired_handler(
    open_store: Callable[[str], AbstractAsyncContextManager[AsyncSession]],
) -> StoreEventHandler:
    """The Connect webhook handler for ``EXPIRED_EVENT_TYPE``.

    Commits only the store session it opens; the write is idempotent, so Stripe's retry after
    a failed platform claim changes nothing.
    """

    async def handle(route: ConnectRoute, obj: Mapping[str, Any]) -> None:
        if route.store_id is None:  # routing always sets one for store-scoped events
            logger.error("checkout expiry event routed without a store")
            report_exception(UnusableExpiredSession("no store"))
            return
        async with open_store(route.store_id) as session:
            await cancel_expired_session_order(session, obj)
            await session.commit()

    return handle


async def _may_cancel(
    stripe: StripeCheckout | None,
    account_id: str | None,
    session_id: str | None,
    order_id: str,
) -> bool:
    """True when no payment can still arrive for the order: no session, or one Stripe expired."""
    if session_id is None:
        return True
    if stripe is None or account_id is None:
        return False
    try:
        outcome = await stripe.expire_session(account_id, session_id)
    except StripeError as exc:
        logger.warning(
            "expired order's session not verified; order left pending: %s",
            type(exc).__name__,
            extra={"order_id": order_id},
        )
        return False
    return outcome is ExpireOutcome.EXPIRED


async def sweep_expired_checkout_orders(
    session: AsyncSession,
    stripe: StripeCheckout | None,
    account_id: str | None,
    *,
    grace: timedelta = SWEEP_GRACE,
    batch: int = SWEEP_BATCH,
    after: SweepCursor | None = None,
    with_sessions: bool = True,
) -> SweepPage:
    """Cancel pending checkout orders whose session is over, one page. Commits.

    Reads up to ``batch`` candidates (``grace`` past their expiry, after ``after``), ends the
    read transaction, then settles each one: see the module docstring. ``examined`` counts the
    candidates read, so a caller pages on until it is below ``batch``. With
    ``with_sessions=False`` only orders that have no session id are candidates, so nothing
    here calls Stripe.
    """
    rows = (
        (
            await session.execute(
                _CANDIDATES_SQL,
                {
                    "grace": grace.total_seconds(),
                    "batch": batch,
                    "after_at": after.expires_at if after else _BEGINNING,
                    "after_id": after.order_id if after else "",
                    "with_sessions": with_sessions,
                },
            )
        )
        .mappings()
        .all()
    )
    await session.rollback()  # no transaction stays open across the Stripe calls below
    cancelled = 0
    for row in rows:
        if not await _may_cancel(stripe, account_id, row["session_id"], row["id"]):
            continue
        if await cancel_pending_order(session, row["id"]):
            cancelled += 1
        await session.commit()
    last = rows[-1] if rows else None
    cursor = SweepCursor(last["expires_at"], last["id"]) if last else None
    return SweepPage(examined=len(rows), cancelled=cancelled, cursor=cursor)
