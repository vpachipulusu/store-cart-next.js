"""Test double for admin subscription management (KAN-48): a recording Stripe admin client.

Behaves like Stripe where it matters to the service: an idempotency key replays the
first answer, and reusing a key for a different request is refused.
"""

from dataclasses import replace
from typing import Any

from app.core.stripe_admin import StripeCharge, StripeRefund
from app.core.stripe_billing import (
    StripeError,
    StripeNotFound,
    StripeRejected,
    StripeSubscription,
)


def charge(**overrides: Any) -> StripeCharge:
    base = StripeCharge(
        id="ch_1",
        customer_id="cus_1",
        amount=5000,
        amount_captured=5000,
        amount_refunded=0,
        currency="gbp",
        status="succeeded",
        captured=True,
        created=1_800_000_000,
        invoice_id="in_1",
    )
    return replace(base, **overrides)


class FakeStripeAdmin:
    """Implements StripeAdminBilling; records every call and can be told to fail."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = False
        self.reject = False
        self.fail_refund = False  # only the refund write fails
        self.missing_subscription = False
        self.refund_refs: dict[str, StripeRefund] = {}
        self.subscription = StripeSubscription(
            "sub_1", "cus_1", "si_1", "price_pro_m", "active", False
        )
        self.charges: dict[str, StripeCharge] = {
            "ch_1": charge(),
            "ch_other": charge(id="ch_other", customer_id="cus_other"),
            "ch_pending": charge(
                id="ch_pending", captured=False, amount_captured=0, status="pending"
            ),
            "ch_refunded": charge(id="ch_refunded", amount_refunded=5000),
        }
        self._refunds: dict[str, tuple[tuple[str, int], StripeRefund]] = {}

    def _record(self, call: str, /, **kwargs: Any) -> None:
        self.calls.append((call, kwargs))
        if self.fail:
            raise StripeError("Stripe request failed")
        if self.reject:
            raise StripeRejected("Stripe request failed")

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def last(self, name: str) -> dict[str, Any]:
        return next(args for call, args in reversed(self.calls) if call == name)

    async def get_subscription(self, subscription_id: str) -> StripeSubscription:
        self._record("get_subscription", subscription_id=subscription_id)
        if self.missing_subscription:
            raise StripeNotFound("Stripe request failed")
        return self.subscription

    async def set_cancel_at_period_end(self, **kwargs: Any) -> None:
        self._record("set_cancel_at_period_end", **kwargs)
        self.subscription = replace(self.subscription, cancel_at_period_end=True)

    async def cancel_subscription(
        self, subscription_id: str, *, idempotency_key: str
    ) -> None:
        self._record(
            "cancel_subscription",
            subscription_id=subscription_id,
            idempotency_key=idempotency_key,
        )
        self.subscription = replace(self.subscription, status="canceled")

    async def list_charges(self, customer_id: str) -> list[StripeCharge]:
        self._record("list_charges", customer_id=customer_id)
        return [c for c in self.charges.values() if c.customer_id == customer_id]

    async def get_charge(self, charge_id: str) -> StripeCharge:
        self._record("get_charge", charge_id=charge_id)
        if charge_id not in self.charges:
            raise StripeNotFound("Stripe request failed")
        return self.charges[charge_id]

    async def create_refund(
        self,
        *,
        charge_id: str,
        amount: int,
        reason: str | None,
        organization_id: str,
        request_ref: str,
        idempotency_key: str,
    ) -> StripeRefund:
        self._record(
            "create_refund",
            charge_id=charge_id,
            amount=amount,
            reason=reason,
            organization_id=organization_id,
            request_ref=request_ref,
            idempotency_key=idempotency_key,
        )
        if self.fail_refund:
            raise StripeError("Stripe request failed")
        signature = (charge_id, amount)
        if idempotency_key in self._refunds:
            first, refund = self._refunds[idempotency_key]
            if first != signature:
                raise StripeRejected("Stripe request failed")
            return refund
        current = self.charges[charge_id]
        if amount > current.refundable:
            raise StripeRejected("Stripe request failed")
        refund = StripeRefund(
            f"re_{len(self._refunds) + 1}", amount, current.currency, "succeeded"
        )
        self._refunds[idempotency_key] = (signature, refund)
        self.refund_refs[request_ref] = refund
        self.charges[charge_id] = replace(
            current, amount_refunded=current.amount_refunded + amount
        )
        return refund

    async def find_refund(
        self, charge_id: str, request_ref: str
    ) -> StripeRefund | None:
        self._record("find_refund", charge_id=charge_id, request_ref=request_ref)
        return self.refund_refs.get(request_ref)

    def forget_idempotency_keys(self) -> None:
        """What Stripe does 24 hours after a request: the key no longer replays."""
        self._refunds.clear()
