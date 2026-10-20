"""Stripe refunds on a merchant's connected account (KAN-80).

Direct charges (plan D4): the payment lives on the connected account, so the refund is made
there (``Stripe-Account`` header), not on the platform. Amounts are integer minor units that the
server computed from the order; nothing here prices anything. The platform's application fee
is not refunded (``refund_application_fee`` is not sent), so the platform keeps its fee unless
the owner decides otherwise.

The metadata carries our ``refund_id`` and ``order_id`` so the Connect webhook (``refund.*``
events) can find the refund again; ``store_id`` routes the event to the store. The idempotency
key is the refund id, so a retry of the same call can never refund twice.

Reuses the Stripe Billing transport (``HttpStripeBilling._call``): same timeout, error mapping
and no-secret logging. Tests inject a fake ``StripeRefunds``.
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.stripe_billing import (
    HttpStripeBilling,
    StripeError,
    StripeNotConfigured,
    require_text,
)


@dataclass(frozen=True)
class RefundRequest:
    account_id: str
    payment_intent_id: str
    amount_minor: int
    store_id: str
    order_id: str
    refund_id: str  # also the idempotency key


@dataclass(frozen=True)
class StripeRefund:
    id: str
    status: str  # pending, requires_action, succeeded, failed or canceled


class StripeRefunds(Protocol):
    async def create_refund(self, request: RefundRequest) -> StripeRefund: ...


def refund_form(request: RefundRequest) -> dict[str, str]:
    """The form body of ``POST /v1/refunds`` for part or all of a payment."""
    return {
        "payment_intent": request.payment_intent_id,
        "amount": str(request.amount_minor),
        "metadata[store_id]": request.store_id,
        "metadata[order_id]": request.order_id,
        "metadata[refund_id]": request.refund_id,
    }


class HttpStripeRefunds(HttpStripeBilling):
    async def create_refund(self, request: RefundRequest) -> StripeRefund:
        body = await self._call(
            "POST",
            "/refunds",
            data=refund_form(request),
            idempotency_key=f"refund-{request.refund_id}",
            stripe_account=request.account_id,
        )
        status = body.get("status")
        if not isinstance(status, str) or not status:
            raise StripeError("Stripe response was unusable")
        return StripeRefund(id=require_text(body.get("id")), status=status)


def get_stripe_refunds() -> StripeRefunds:
    """The one place the real client is built; tests override the dependency that calls it."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
    return HttpStripeRefunds(secret.get_secret_value())
