"""Stripe calls for platform-admin subscription management (KAN-48).

Extends the organisation-billing client with the few extra calls an admin needs:
read a customer's charges, refund a charge, and cancel a subscription at once. Same
rules as ``stripe_billing``: no Stripe text reaches a log or a response, every write
carries an idempotency key. Only money fields of a charge are kept; card and billing
details are never parsed.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings
from app.core.stripe_billing import (
    HttpStripeBilling,
    StripeError,
    StripeNotConfigured,
    StripeSubscription,
    as_int,
    as_text,
    require_text,
)

CHARGE_LIST_LIMIT = 12


@dataclass(frozen=True)
class StripeCharge:
    id: str
    customer_id: str | None
    amount: int
    amount_captured: int
    amount_refunded: int
    currency: str
    status: str | None
    captured: bool
    created: int
    invoice_id: str | None

    @property
    def refundable(self) -> int:
        """Minor units still refundable (0 for an uncaptured or unsuccessful charge)."""
        if not self.captured or self.status != "succeeded":
            return 0
        return max(self.amount_captured - self.amount_refunded, 0)


@dataclass(frozen=True)
class StripeRefund:
    id: str
    amount: int
    currency: str
    status: str | None


class StripeAdminBilling(Protocol):
    async def get_subscription(self, subscription_id: str) -> StripeSubscription: ...

    async def set_cancel_at_period_end(
        self, *, subscription_id: str, cancel: bool, idempotency_key: str
    ) -> None: ...

    async def cancel_subscription(
        self, subscription_id: str, *, idempotency_key: str
    ) -> None: ...

    async def list_charges(self, customer_id: str) -> list[StripeCharge]: ...

    async def get_charge(self, charge_id: str) -> StripeCharge: ...

    async def create_refund(
        self,
        *,
        charge_id: str,
        amount: int,
        reason: str | None,
        organization_id: str,
        request_ref: str,
        idempotency_key: str,
    ) -> StripeRefund: ...

    async def find_refund(
        self, charge_id: str, request_ref: str
    ) -> StripeRefund | None: ...


def _id_of(value: Any) -> str | None:
    """An id that Stripe returns either bare or as an expanded object."""
    if isinstance(value, dict):
        value = value.get("id")
    return as_text(value)


def _charge(row: dict[str, Any]) -> StripeCharge:
    return StripeCharge(
        id=require_text(row.get("id")),
        customer_id=_id_of(row.get("customer")),
        amount=as_int(row.get("amount")),
        amount_captured=as_int(row.get("amount_captured")),
        amount_refunded=as_int(row.get("amount_refunded")),
        currency=as_text(row.get("currency")) or "",
        status=as_text(row.get("status")),
        captured=row.get("captured") is True,
        created=as_int(row.get("created")),
        invoice_id=_id_of(row.get("invoice")),
    )


def _refund(body: dict[str, Any]) -> StripeRefund:
    refund_amount = as_int(body.get("amount"))
    if refund_amount <= 0:
        raise StripeError("Stripe response was unusable")
    return StripeRefund(
        id=require_text(body.get("id")),
        amount=refund_amount,
        currency=as_text(body.get("currency")) or "",
        status=as_text(body.get("status")),
    )


class HttpStripeAdmin(HttpStripeBilling):
    async def cancel_subscription(
        self, subscription_id: str, *, idempotency_key: str
    ) -> None:
        await self._call(
            "DELETE",
            f"/subscriptions/{subscription_id}",
            idempotency_key=idempotency_key,
        )

    async def list_charges(self, customer_id: str) -> list[StripeCharge]:
        body = await self._call(
            "GET",
            "/charges",
            params={"customer": customer_id, "limit": str(CHARGE_LIST_LIMIT)},
        )
        return [_charge(row) for row in body.get("data") or [] if isinstance(row, dict)]

    async def get_charge(self, charge_id: str) -> StripeCharge:
        return _charge(await self._call("GET", f"/charges/{charge_id}"))

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
        data = {
            "charge": charge_id,
            "amount": str(amount),
            "metadata[organization_id]": organization_id,
            "metadata[request_ref]": request_ref,
        }
        if reason:
            data["reason"] = reason
        body = await self._call(
            "POST", "/refunds", data=data, idempotency_key=idempotency_key
        )
        return _refund(body)

    async def find_refund(
        self, charge_id: str, request_ref: str
    ) -> StripeRefund | None:
        body = await self._call(
            "GET", "/refunds", params={"charge": charge_id, "limit": "100"}
        )
        for row in body.get("data") or []:
            metadata = row.get("metadata") if isinstance(row, dict) else None
            if (
                isinstance(metadata, dict)
                and metadata.get("request_ref") == request_ref
            ):
                return _refund(row)
        return None


def get_stripe_admin() -> StripeAdminBilling:
    """The one place the real admin client is built; tests override the dependency."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
    return HttpStripeAdmin(secret.get_secret_value())
