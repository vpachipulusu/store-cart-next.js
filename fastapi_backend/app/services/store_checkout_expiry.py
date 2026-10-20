"""Expiry of unpaid checkout orders (KAN-256). No FastAPI imports.

A checkout order is ``pending`` until its Stripe Checkout Session is paid. The session is
created with an explicit ``expires_at`` (``SESSION_LIFETIME``, stored on the order as
``checkout_expires_at``), so every unpaid order ends:

* ``checkout.session.expired`` (Connect webhook) cancels the order linked to that session
  while it is still ``pending``. One conditional ``UPDATE``: a redelivery, a paid order and
  an order linked to another session are all left alone.
* The sweep is the backstop for a lost event and for an order that never got a session link:
  it cancels pending orders ``SWEEP_GRACE`` past ``checkout_expires_at``. The grace covers
  clock skew and a payment that completes at the last second (its webhook still finds the
  order pending and pays it). Checkout runs the sweep for its own store before it starts, and
  ``commands.sweep_checkout_orders`` runs it for every ACTIVE store.

Neither calls Stripe: a session past ``expires_at`` can no longer be paid.
"""

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sentry import report_exception
from app.repositories.connect_events import ConnectRoute
from app.services.stripe_connect import StoreEventHandler

logger = logging.getLogger(__name__)

EXPIRED_EVENT_TYPE = "checkout.session.expired"
# Stripe accepts an expiry from 30 minutes to 24 hours after the session is created; the extra
# minutes cover the time between writing the order and Stripe receiving the request.
SESSION_LIFETIME = timedelta(minutes=35)
SWEEP_GRACE = timedelta(minutes=10)
SWEEP_BATCH = 200
SESSION_ID_MAX_LENGTH = 255

_CANCEL_EXPIRED_SQL = text(
    "UPDATE orders SET status = 'cancelled', updated_at = now() "
    "WHERE stripe_checkout_session_id = :session_id AND status = 'pending' "
    "RETURNING id"
)
_SWEEP_SQL = text(
    "UPDATE orders SET status = 'cancelled', updated_at = now() "
    "WHERE id IN (SELECT id FROM orders WHERE status = 'pending'"
    " AND checkout_expires_at IS NOT NULL"
    " AND checkout_expires_at < now() - make_interval(secs => :grace)"
    " ORDER BY checkout_expires_at LIMIT :batch FOR UPDATE SKIP LOCKED) "
    "AND status = 'pending' RETURNING id"
)


class UnusableExpiredSession(Exception):
    """A ``checkout.session.expired`` event with no usable session id (Sentry only)."""


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


async def sweep_expired_checkout_orders(
    session: AsyncSession,
    *,
    grace: timedelta = SWEEP_GRACE,
    batch: int = SWEEP_BATCH,
) -> int:
    """Cancel pending checkout orders whose session ended ``grace`` ago. Does not commit.

    At most ``batch`` orders per call, oldest first; rows another sweep holds are skipped.
    Returns the number cancelled.
    """
    rows = await session.execute(
        _SWEEP_SQL, {"grace": grace.total_seconds(), "batch": batch}
    )
    return len(rows.all())
