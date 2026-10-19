"""Stripe Billing client for organisation billing (KAN-43).

``StripeBilling`` is the seam the service depends on; tests inject a fake. The real
client talks to the Stripe REST API with httpx. It never logs requests, responses or
the secret key, and every failure becomes a ``StripeError`` that carries no Stripe
text, so nothing from Stripe can reach a log line or a response body.
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger("storecart.stripe_billing")
# httpx logs every request line at INFO, including query strings such as
# ?customer=cus_...; keep customer ids out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

STRIPE_API = "https://api.stripe.com/v1"
REQUEST_TIMEOUT_SECONDS = 10.0
LIST_LIMIT = 12
REJECTED_STATUSES = frozenset({400, 402, 409})
NOT_PROCESSED_STATUSES = frozenset({401, 429})
# Stripe's error `type` and `code` are fixed snake_case enums; anything else is dropped, never logged.
ERROR_TOKEN = re.compile(r"[a-z0-9_]{1,64}")


class StripeError(Exception):
    """Any failed Stripe call; the message never contains Stripe output."""


class StripeNotConfigured(StripeError):
    """STRIPE_SECRET_KEY is not set."""


class StripeNotFound(StripeError):
    """Stripe has no such object (HTTP 404)."""


class StripeForbidden(StripeError):
    """Stripe refused access to the object (HTTP 403), e.g. an account that revoked the platform."""


class StripeRejected(StripeError):
    """Stripe refused the request itself (HTTP 400, 402 or 409), not an outage."""


class StripeConflict(StripeRejected):
    """HTTP 409: for example a request with the same idempotency key is still in flight."""


class StripeNotProcessed(StripeError):
    """HTTP 401 or 429: Stripe did not process the request (bad key, rate limited).

    Not a ``StripeRejected``: callers that treat a refusal as final keep treating these as
    retryable outages; checkout uses it to know no session was created.
    """


@dataclass(frozen=True)
class StripeSubscription:
    id: str
    customer_id: str
    item_id: str | None
    price_id: str | None
    status: str | None = None
    cancel_at_period_end: bool = False


@dataclass(frozen=True)
class StripeInvoice:
    id: str
    number: str | None
    status: str | None
    amount_due: int
    amount_paid: int
    currency: str
    created: int
    hosted_invoice_url: str | None
    invoice_pdf: str | None


@dataclass(frozen=True)
class StripePaymentMethod:
    id: str
    brand: str | None
    last4: str | None
    exp_month: int | None
    exp_year: int | None
    is_default: bool = False


class StripeBilling(Protocol):
    async def create_customer(
        self, *, name: str, organization_id: str, idempotency_key: str
    ) -> str: ...

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        organization_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> str: ...

    async def create_portal_session(
        self, *, customer_id: str, return_url: str, idempotency_key: str
    ) -> str: ...

    async def get_subscription(self, subscription_id: str) -> StripeSubscription: ...

    async def change_subscription_price(
        self,
        *,
        subscription_id: str,
        item_id: str,
        price_id: str,
        idempotency_key: str,
    ) -> None: ...

    async def set_cancel_at_period_end(
        self, *, subscription_id: str, cancel: bool, idempotency_key: str
    ) -> None: ...

    async def list_invoices(self, customer_id: str) -> list[StripeInvoice]: ...

    async def list_payment_methods(
        self, customer_id: str
    ) -> list[StripePaymentMethod]: ...

    async def get_default_payment_method_id(self, customer_id: str) -> str | None: ...

    async def get_payment_method_customer_id(
        self, payment_method_id: str
    ) -> str | None:
        """The customer a payment method is attached to; StripeNotFound if unknown."""
        ...

    async def detach_payment_method(
        self, *, payment_method_id: str, idempotency_key: str
    ) -> None: ...

    async def set_default_payment_method(
        self, *, customer_id: str, payment_method_id: str, idempotency_key: str
    ) -> None: ...


def as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def as_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def require_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise StripeError("Stripe response was unusable")
    return value


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _error_detail(response: httpx.Response) -> str:
    """` type=... code=...` from Stripe's error body when both are plain enum tokens; else empty."""
    try:
        error = as_dict(response.json()).get("error")
    except ValueError:
        return ""
    fields = as_dict(error)
    parts = []
    for name in ("type", "code"):
        value = fields.get(name)
        if isinstance(value, str) and ERROR_TOKEN.fullmatch(value):
            parts.append(f" {name}={value}")
    return "".join(parts)


class HttpStripeBilling:
    def __init__(self, secret_key: str, client: httpx.AsyncClient | None = None):
        self._key = secret_key
        self._client = client

    async def _send(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        data: Mapping[str, str] | None,
        params: Mapping[str, str] | None,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        return await client.request(
            method,
            f"{STRIPE_API}{path}",
            data=data,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
        stripe_account: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if stripe_account:
            # Act on the connected account (direct charges, KAN-68).
            headers["Stripe-Account"] = stripe_account
        try:
            if self._client is not None:
                response = await self._send(
                    self._client, method, path, data, params, headers
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await self._send(
                        client, method, path, data, params, headers
                    )
            if response.status_code >= 400:
                logger.warning(
                    "stripe call failed: status=%s%s",
                    response.status_code,
                    _error_detail(response),
                )
                if response.status_code == 404:
                    raise StripeNotFound("Stripe request failed")
                if response.status_code == 403:
                    raise StripeForbidden("Stripe request failed")
                if response.status_code == 409:
                    raise StripeConflict("Stripe request failed")
                if response.status_code in NOT_PROCESSED_STATUSES:
                    raise StripeNotProcessed("Stripe request failed")
                if response.status_code in REJECTED_STATUSES:
                    raise StripeRejected("Stripe request failed")
                raise StripeError("Stripe request failed")
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("stripe call failed: %s", type(exc).__name__)
            raise StripeError("Stripe request failed") from None
        if not isinstance(body, dict):
            raise StripeError("Stripe request failed")
        return body

    async def create_customer(
        self, *, name: str, organization_id: str, idempotency_key: str
    ) -> str:
        body = await self._call(
            "POST",
            "/customers",
            data={"name": name[:256], "metadata[organization_id]": organization_id},
            idempotency_key=idempotency_key,
        )
        return require_text(body.get("id"))

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        organization_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> str:
        body = await self._call(
            "POST",
            "/checkout/sessions",
            data={
                "mode": "subscription",
                "customer": customer_id,
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "client_reference_id": organization_id,
                "subscription_data[metadata][organization_id]": organization_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
            idempotency_key=idempotency_key,
        )
        return require_text(body.get("url"))

    async def create_portal_session(
        self, *, customer_id: str, return_url: str, idempotency_key: str
    ) -> str:
        body = await self._call(
            "POST",
            "/billing_portal/sessions",
            data={"customer": customer_id, "return_url": return_url},
            idempotency_key=idempotency_key,
        )
        return require_text(body.get("url"))

    async def get_subscription(self, subscription_id: str) -> StripeSubscription:
        body = await self._call("GET", f"/subscriptions/{subscription_id}")
        items = as_dict(body.get("items")).get("data") or []
        first = as_dict(items[0]) if items else {}
        return StripeSubscription(
            id=require_text(body.get("id")),
            customer_id=require_text(body.get("customer")),
            item_id=as_text(first.get("id")),
            price_id=as_text(as_dict(first.get("price")).get("id")),
            status=as_text(body.get("status")),
            cancel_at_period_end=body.get("cancel_at_period_end") is True
            or isinstance(body.get("cancel_at"), int),
        )

    async def change_subscription_price(
        self,
        *,
        subscription_id: str,
        item_id: str,
        price_id: str,
        idempotency_key: str,
    ) -> None:
        await self._call(
            "POST",
            f"/subscriptions/{subscription_id}",
            data={
                "items[0][id]": item_id,
                "items[0][price]": price_id,
                "proration_behavior": "create_prorations",
            },
            idempotency_key=idempotency_key,
        )

    async def set_cancel_at_period_end(
        self, *, subscription_id: str, cancel: bool, idempotency_key: str
    ) -> None:
        await self._call(
            "POST",
            f"/subscriptions/{subscription_id}",
            data={"cancel_at_period_end": "true" if cancel else "false"},
            idempotency_key=idempotency_key,
        )

    async def list_invoices(self, customer_id: str) -> list[StripeInvoice]:
        body = await self._call(
            "GET",
            "/invoices",
            params={"customer": customer_id, "limit": str(LIST_LIMIT)},
        )
        return [
            StripeInvoice(
                id=require_text(row.get("id")),
                number=as_text(row.get("number")),
                status=as_text(row.get("status")),
                amount_due=as_int(row.get("amount_due")),
                amount_paid=as_int(row.get("amount_paid")),
                currency=as_text(row.get("currency")) or "",
                created=as_int(row.get("created")),
                hosted_invoice_url=as_text(row.get("hosted_invoice_url")),
                invoice_pdf=as_text(row.get("invoice_pdf")),
            )
            for row in body.get("data") or []
            if isinstance(row, dict)
        ]

    async def list_payment_methods(self, customer_id: str) -> list[StripePaymentMethod]:
        body = await self._call(
            "GET",
            "/payment_methods",
            params={"customer": customer_id, "type": "card", "limit": str(LIST_LIMIT)},
        )
        methods = []
        for row in body.get("data") or []:
            if not isinstance(row, dict):
                continue
            card = as_dict(row.get("card"))
            methods.append(
                StripePaymentMethod(
                    id=require_text(row.get("id")),
                    brand=as_text(card.get("brand")),
                    last4=as_text(card.get("last4")),
                    exp_month=as_int(card.get("exp_month")) or None,
                    exp_year=as_int(card.get("exp_year")) or None,
                )
            )
        return methods

    async def get_default_payment_method_id(self, customer_id: str) -> str | None:
        body = await self._call("GET", f"/customers/{customer_id}")
        default = as_dict(body.get("invoice_settings")).get("default_payment_method")
        # Stripe returns an id, or the whole object when expanded.
        return as_text(
            as_dict(default).get("id") if isinstance(default, dict) else default
        )

    async def get_payment_method_customer_id(
        self, payment_method_id: str
    ) -> str | None:
        body = await self._call("GET", f"/payment_methods/{payment_method_id}")
        customer = body.get("customer")
        if isinstance(customer, dict):
            customer = customer.get("id")
        return as_text(customer)

    async def detach_payment_method(
        self, *, payment_method_id: str, idempotency_key: str
    ) -> None:
        await self._call(
            "POST",
            f"/payment_methods/{payment_method_id}/detach",
            idempotency_key=idempotency_key,
        )

    async def set_default_payment_method(
        self, *, customer_id: str, payment_method_id: str, idempotency_key: str
    ) -> None:
        await self._call(
            "POST",
            f"/customers/{customer_id}",
            data={"invoice_settings[default_payment_method]": payment_method_id},
            idempotency_key=idempotency_key,
        )


def get_stripe_billing() -> StripeBilling:
    """The one place the real client is built; tests override this dependency."""
    secret = settings.STRIPE_SECRET_KEY
    if secret is None or not secret.get_secret_value():
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
    return HttpStripeBilling(secret.get_secret_value())
