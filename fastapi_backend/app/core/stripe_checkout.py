"""Stripe Checkout Sessions on a merchant's connected account (KAN-68).

Direct charges: the session is created on the connected account (``Stripe-Account`` header),
so the merchant is the merchant of record and the payment, its Stripe fees and refunds live on
their account. ``application_fee_amount`` is sent only when a platform fee applies. Amounts are
integer minor units computed on the server; nothing here prices anything.

Reuses the Stripe Billing transport (``HttpStripeBilling._call``): same timeout, error mapping
and no-secret logging. Tests inject a fake ``StripeCheckout``.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.config import settings
from app.core.stripe_billing import (
    HttpStripeBilling,
    StripeError,
    StripeNotConfigured,
    StripeNotFound,
    StripeRejected,
    require_text,
)

MAX_NAME_LENGTH = 250


@dataclass(frozen=True)
class CheckoutLineItem:
    name: str
    unit_amount_minor: int
    quantity: int


@dataclass(frozen=True)
class CheckoutSessionRequest:
    account_id: str
    currency: str  # lower-case ISO 4217, as Stripe expects
    line_items: tuple[CheckoutLineItem, ...]
    application_fee_minor: int | None  # None: no platform fee, the field is not sent
    store_id: str
    order_id: str
    success_url: str
    cancel_url: str
    idempotency_key: str
    expires_at: int | None = None  # Unix seconds; None leaves Stripe's 24 hour default


@dataclass(frozen=True)
class StripeCheckoutSession:
    id: str
    url: str


class ExpireOutcome(StrEnum):
    EXPIRED = "expired"  # the session can no longer be paid (now, or already)
    COMPLETE = "complete"  # the shopper paid it: the order must not be cancelled


class StripeCheckout(Protocol):
    async def create_payment_session(
        self, request: CheckoutSessionRequest
    ) -> StripeCheckoutSession: ...

    async def expire_session(
        self, account_id: str, session_id: str
    ) -> ExpireOutcome: ...


def session_form(request: CheckoutSessionRequest) -> dict[str, str]:
    """The form body of ``POST /v1/checkout/sessions`` for a one-off payment."""
    data = {
        "mode": "payment",
        "success_url": request.success_url,
        "cancel_url": request.cancel_url,
        "client_reference_id": request.order_id,
        "metadata[store_id]": request.store_id,
        "metadata[order_id]": request.order_id,
        "payment_intent_data[metadata][store_id]": request.store_id,
        "payment_intent_data[metadata][order_id]": request.order_id,
    }
    for index, line in enumerate(request.line_items):
        prefix = f"line_items[{index}]"
        data[f"{prefix}[quantity]"] = str(line.quantity)
        data[f"{prefix}[price_data][currency]"] = request.currency
        data[f"{prefix}[price_data][unit_amount]"] = str(line.unit_amount_minor)
        data[f"{prefix}[price_data][product_data][name]"] = line.name[:MAX_NAME_LENGTH]
    if request.expires_at is not None:
        data["expires_at"] = str(request.expires_at)
    if request.application_fee_minor:
        data["payment_intent_data[application_fee_amount]"] = str(
            request.application_fee_minor
        )
    return data


class HttpStripeCheckout(HttpStripeBilling):
    async def create_payment_session(
        self, request: CheckoutSessionRequest
    ) -> StripeCheckoutSession:
        body = await self._call(
            "POST",
            "/checkout/sessions",
            data=session_form(request),
            idempotency_key=request.idempotency_key,
            stripe_account=request.account_id,
        )
        session_id = require_text(body.get("id"))
        url = require_text(body.get("url"))
        if not url.startswith("https://"):
            raise StripeError("Stripe response was unusable")
        return StripeCheckoutSession(id=session_id, url=url)

    async def expire_session(self, account_id: str, session_id: str) -> ExpireOutcome:
        """Make an open session unpayable (``POST /v1/checkout/sessions/{id}/expire``).

        Stripe refuses to expire a session that is not open (400). Then the session is read:
        already expired is the wanted state, complete means the shopper paid. A session
        Stripe does not know (404) cannot be paid. Any other failure propagates: the caller
        must not assume the session is closed.

        No idempotency key: expiring is idempotent by nature, and Stripe would replay a 5xx
        for a key and block every retry.
        """
        path = f"/checkout/sessions/{session_id}"
        try:
            await self._call(
                "POST",
                f"{path}/expire",
                data={},
                stripe_account=account_id,
            )
        except StripeNotFound:
            return ExpireOutcome.EXPIRED
        except StripeRejected:
            body = await self._call("GET", path, stripe_account=account_id)
            status = body.get("status")
            if status == "expired":
                return ExpireOutcome.EXPIRED
            if status == "complete":
                return ExpireOutcome.COMPLETE
            raise
        return ExpireOutcome.EXPIRED


def get_stripe_checkout() -> StripeCheckout:
    """The one place the real client is built; tests override the dependency that calls it."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
    return HttpStripeCheckout(secret.get_secret_value())
