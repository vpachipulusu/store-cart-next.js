"""A merchant cancels a pending order (KAN-256). No FastAPI imports.

An order is ``pending`` while its Stripe Checkout Session can still be paid, so cancelling the
row alone would let the shopper pay a cancelled order (a manual refund). The session is made
unpayable first (``POST /v1/checkout/sessions/{id}/expire`` on the merchant's connected
account), and only then is the order cancelled, with one conditional ``UPDATE``:

* the session is already complete (the shopper paid): the order is left alone (409), the
  webhook is about to pay it;
* Stripe cannot be reached or refuses: the order stays ``pending`` (502), nothing is assumed;
* an order whose session is unknown while its expiry has not passed may still have one at
  Stripe, so it is not cancelled yet (502); once it has expired it is, and so is an order that
  never went through checkout (no expiry).

Only pending orders can be cancelled here: refunding a paid order is ``merchant_order_refund``.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stripe_billing import StripeError
from app.core.stripe_checkout import ExpireOutcome, StripeCheckout
from app.services.merchant_orders import OrderDetail, StoreOrdersService
from app.services.store_orders import (
    OrderError,
    OrderNotFound,
    OrderStatus,
    cancel_pending_order,
)

logger = logging.getLogger(__name__)

_STATE_SQL = text(
    "SELECT status, stripe_checkout_session_id, checkout_expires_at "
    "FROM orders WHERE id = :id"
)


class OrderNotCancellable(OrderError):
    """Only a pending order can be cancelled (HTTP 409)."""


class OrderPaymentInProgress(OrderError):
    """The shopper paid the order's session; it is about to become paid (HTTP 409)."""


class OrderCancelUnavailable(OrderError):
    """The order's payment page could not be closed; nothing changed (HTTP 502)."""


class MerchantOrderCancelService:
    def __init__(
        self,
        orders: StoreOrdersService,
        session: AsyncSession,
        stripe: StripeCheckout,
        account_id: str | None,
    ) -> None:
        self._orders = orders
        self._session = session
        self._stripe = stripe
        self._account_id = account_id

    async def cancel(self, order_id: str) -> OrderDetail:
        state = (
            (await self._session.execute(_STATE_SQL, {"id": order_id}))
            .mappings()
            .first()
        )
        if state is None:
            raise OrderNotFound(order_id)
        if state["status"] != OrderStatus.PENDING.value:
            raise OrderNotCancellable("Only a pending order can be cancelled")
        await self._session.rollback()  # no transaction open across the Stripe call
        await self._close_session(
            state["stripe_checkout_session_id"], state["checkout_expires_at"]
        )
        try:
            cancelled = await cancel_pending_order(self._session, order_id)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        if not cancelled:  # paid or cancelled between the read and the write
            raise OrderNotCancellable("Only a pending order can be cancelled")
        return await self._orders.get(order_id)

    async def _close_session(
        self, session_id: str | None, expires_at: datetime | None
    ) -> None:
        if session_id is None:
            if expires_at is not None and expires_at > datetime.now(UTC):
                raise OrderCancelUnavailable("The payment page could not be closed")
            return
        if self._account_id is None:
            raise OrderCancelUnavailable("The payment page could not be closed")
        try:
            outcome = await self._stripe.expire_session(self._account_id, session_id)
        except StripeError:
            logger.warning("checkout session not expired; order not cancelled")
            raise OrderCancelUnavailable(
                "The payment page could not be closed"
            ) from None
        if outcome is ExpireOutcome.COMPLETE:
            raise OrderPaymentInProgress("The order's payment is being processed")
