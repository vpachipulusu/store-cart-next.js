"""A merchant refunds a paid order, in full or by lines, through the connected account (KAN-80).

No FastAPI imports. The steps, each in its own transaction so none is open across Stripe:

1. ``reserve_refund`` records a ``pending`` refund and commits. It counts against the order
   at once, so a second request cannot refund the same units while Stripe is being asked.
2. Stripe is asked to refund the payment on the merchant's account (idempotency key = the
   refund id). Money moves there, not here.
3. Stripe's answer settles the refund: ``succeeded`` or a definite refusal settles it now; a
   refund Stripe still processes stays ``pending`` and the Connect webhook (``refund.*``)
   settles it later. Both paths call ``settle_refund``, which changes the refund once, so
   the response and the webhook can race harmlessly. Restock and the order status change
   are part of that settlement.

When Stripe cannot be reached or answers with an error that does not say the refund was
refused, the outcome is unknown, so the refund stays ``pending`` (nothing is released) and
the merchant gets a 502: the refund may still have happened, and the webhook settles it if
it did. A definite refusal (Stripe rejected the request, or did not process it) releases
the reservation.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stripe_billing import (
    StripeConflict,
    StripeError,
    StripeForbidden,
    StripeNotConfigured,
    StripeNotFound,
    StripeNotProcessed,
    StripeRejected,
)
from app.core.stripe_refunds import RefundRequest, StripeRefunds
from app.services.merchant_orders import OrderDetail, StoreOrdersService
from app.services.store_orders import OrderError
from app.services.store_refunds import (
    RefundLineInput,
    RefundOutcome,
    RefundPlan,
    record_stripe_refund,
    reserve_refund,
    settle_refund,
)

logger = logging.getLogger(__name__)

# Stripe refund statuses that end the refund for good, and the one that completes it.
_SUCCEEDED = "succeeded"
_FAILED = frozenset({"failed", "canceled"})
# Errors that say Stripe did not (and will not) make this refund.
_REFUSED = (
    StripeRejected,
    StripeNotFound,
    StripeForbidden,
    StripeNotProcessed,
    StripeNotConfigured,
)


class RefundUnavailable(OrderError):
    """Stripe could not be asked, or its answer is unknown (HTTP 502)."""


class RefundRefused(OrderError):
    """Stripe refused the refund; nothing was refunded (HTTP 409)."""


class MerchantOrderRefundService:
    def __init__(
        self,
        orders: StoreOrdersService,
        session: AsyncSession,
        stripe: StripeRefunds,
        store_id: str,
        account_id: str | None,
    ) -> None:
        self._orders = orders
        self._session = session
        self._stripe = stripe
        self._store_id = store_id
        self._account_id = account_id

    async def refund(
        self,
        order_id: str,
        lines: list[RefundLineInput] | None,
        *,
        restock: bool = False,
    ) -> OrderDetail:
        if self._account_id is None:
            raise RefundUnavailable("The payment account is not connected")
        plan = await self._reserve(order_id, lines, restock)
        await self._ask_stripe(plan, self._account_id)
        return await self._orders.get(order_id)

    async def _reserve(
        self, order_id: str, lines: list[RefundLineInput] | None, restock: bool
    ) -> RefundPlan:
        try:
            plan = await reserve_refund(self._session, order_id, lines, restock=restock)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return plan

    async def _ask_stripe(self, plan: RefundPlan, account_id: str) -> None:
        request = RefundRequest(
            account_id=account_id,
            payment_intent_id=plan.payment_intent_id,
            amount_minor=plan.amount_minor,
            store_id=self._store_id,
            order_id=plan.order_id,
            refund_id=plan.id,
        )
        try:
            created = await self._stripe.create_refund(request)
        except StripeConflict:  # the same call is still in flight: unknown
            raise RefundUnavailable("The refund is being processed") from None
        except _REFUSED as exc:
            logger.warning("refund refused by stripe: %s", type(exc).__name__)
            await self._settle(plan, RefundOutcome.FAILED, None)
            raise RefundRefused("Stripe could not refund this payment") from None
        except StripeError as exc:
            logger.warning(
                "refund outcome unknown: %s",
                type(exc).__name__,
                extra={"refund_id": plan.id},
            )
            raise RefundUnavailable("The refund could not be confirmed") from None
        if created.status == _SUCCEEDED:
            await self._settle(plan, RefundOutcome.SUCCEEDED, created.id)
        elif created.status in _FAILED:
            await self._settle(plan, RefundOutcome.FAILED, created.id)
            raise RefundRefused("Stripe could not refund this payment")
        else:  # still processing: the webhook settles it
            await self._record(plan, created.id)

    async def _settle(
        self, plan: RefundPlan, outcome: RefundOutcome, stripe_refund_id: str | None
    ) -> None:
        try:
            await settle_refund(
                self._session, plan.id, outcome, stripe_refund_id=stripe_refund_id
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def _record(self, plan: RefundPlan, stripe_refund_id: str) -> None:
        try:
            await record_stripe_refund(self._session, plan.id, stripe_refund_id)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
