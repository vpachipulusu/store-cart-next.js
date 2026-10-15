"""Organisation billing (KAN-43): checkout, portal, plan change, cancel, resume, invoices, payment methods.

Every method first calls ``authorize``: the caller must belong to the organisation
(otherwise it is "not found", so one organisation cannot learn another exists) and
hold the OWNER or ADMIN role (otherwise forbidden).

This service never writes subscription state. Checkout, plan changes and
cancellation only ask Stripe to act; the Stripe webhook (KAN-44) is the single
writer of tier, status and period. The one write here is saving the Stripe customer
id before the first Checkout, which the webhook needs to find the organisation.
"""

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.plans import PLANS, Plan, PlanKey
from app.core.stripe_billing import (
    StripeBilling,
    StripeError,
    StripeInvoice,
    StripeNotFound,
    StripePaymentMethod,
)
from app.models.platform.membership import MembershipRole
from app.repositories.org_billing import OrgBillingRecord

BILLING_ROLES = frozenset({MembershipRole.OWNER, MembershipRole.ADMIN})
# Stripe statuses where a subscription still exists (even if unpaid or paused): a new
# Checkout would create a second one, so use the portal or change/cancel instead.
PAYING_STATUSES = frozenset(
    {"active", "trialing", "past_due", "unpaid", "incomplete", "paused"}
)
PAID_PLANS = frozenset({PlanKey.PRO, PlanKey.ENTERPRISE})
MAX_URL_LENGTH = 2048

PriceCatalogue = Mapping[tuple[PlanKey, str], str]


class OrganizationNotFound(Exception):
    """No such organisation, or the caller is not a member (404)."""


class BillingForbidden(Exception):
    """A member without the OWNER or ADMIN role (403)."""


class BillingConflict(Exception):
    """The request does not fit the organisation's current subscription (409)."""


class PaymentMethodNotFound(Exception):
    """No such payment method on this organisation's customer (404).

    Raised for an unknown id and for one that belongs to another customer alike.
    """


class InvalidReturnUrl(Exception):
    """The return URL is not on the allow-list (422)."""


class BillingUnavailable(Exception):
    """A Stripe call failed (502)."""


class BillingNotConfigured(Exception):
    """A needed Stripe price id is not set (503)."""


class BillingStore(Protocol):
    async def get_role(
        self, organization_id: str, user_id: str
    ) -> MembershipRole | None: ...

    async def get(self, organization_id: str) -> OrgBillingRecord | None: ...

    async def link_customer(self, organization_id: str, customer_id: str) -> str: ...


@dataclass(frozen=True)
class BillingSummary:
    plan: Plan
    status: str
    current_period_end: datetime | None
    has_billing_account: bool
    has_subscription: bool
    cancel_at_period_end: bool
    interval: str | None


def allowed_origins(raw: str) -> frozenset[str]:
    """Normalise the comma separated BILLING_RETURN_URL_ORIGINS setting."""
    return frozenset(
        item.strip().rstrip("/").lower() for item in raw.split(",") if item.strip()
    )


def validate_return_url(url: str, origins: frozenset[str]) -> str:
    """Accept only an http(s) URL whose origin is on the allow-list (no open redirect)."""
    if not url or len(url) > MAX_URL_LENGTH or any(c in url for c in "\\\r\n\t "):
        raise InvalidReturnUrl
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise InvalidReturnUrl from None
    if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc:
        raise InvalidReturnUrl
    origin = f"{parts.scheme}://{host}" + (f":{port}" if port else "")
    if origin.lower() not in origins:
        raise InvalidReturnUrl
    return url


async def _stripe_call[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except StripeError:
        raise BillingUnavailable from None


def _key(operation: str, organization_id: str, request_key: str | None) -> str:
    return f"sc-{operation}-{organization_id}-{request_key or new_id()}"


def _has_live_subscription(record: OrgBillingRecord) -> bool:
    return (
        record.stripe_subscription_id is not None
        and record.subscription_status in PAYING_STATUSES
    )


class OrgBillingService:
    def __init__(
        self,
        store: BillingStore,
        session: AsyncSession,
        stripe: StripeBilling,
        prices: PriceCatalogue,
        origins: frozenset[str],
    ) -> None:
        self._store = store
        self._session = session
        self._stripe = stripe
        self._prices = prices
        self._origins = origins

    async def authorize(self, organization_id: str, user_id: str) -> OrgBillingRecord:
        role = await self._store.get_role(organization_id, user_id)
        if role is None:
            raise OrganizationNotFound
        if role not in BILLING_ROLES:
            raise BillingForbidden
        record = await self._store.get(organization_id)
        if record is None:
            raise OrganizationNotFound
        # End the read transaction so no connection is held while Stripe is called.
        await self._session.rollback()
        return record

    async def summary(self, organization_id: str, user_id: str) -> BillingSummary:
        record = await self.authorize(organization_id, user_id)
        try:
            plan = PLANS[PlanKey(record.subscription_tier)]
        except ValueError:
            plan = PLANS[PlanKey.FREE]
        return BillingSummary(
            plan=plan,
            status=record.subscription_status,
            current_period_end=record.stripe_current_period_end,
            has_billing_account=record.stripe_customer_id is not None,
            has_subscription=record.stripe_subscription_id is not None,
            cancel_at_period_end=record.stripe_cancel_at_period_end,
            interval=self._interval(record.stripe_price_id),
        )

    async def start_checkout(
        self,
        organization_id: str,
        user_id: str,
        *,
        plan: PlanKey,
        interval: str,
        success_url: str,
        cancel_url: str,
        request_key: str | None,
    ) -> str:
        record = await self.authorize(organization_id, user_id)
        success = validate_return_url(success_url, self._origins)
        cancel = validate_return_url(cancel_url, self._origins)
        if plan not in PAID_PLANS or _has_live_subscription(record):
            raise BillingConflict
        price = self._price(plan, interval)
        customer = await self._ensure_customer(record)
        return await _stripe_call(
            self._stripe.create_checkout_session(
                customer_id=customer,
                price_id=price,
                organization_id=record.id,
                success_url=success,
                cancel_url=cancel,
                idempotency_key=_key("checkout", record.id, request_key),
            )
        )

    async def open_portal(
        self,
        organization_id: str,
        user_id: str,
        *,
        return_url: str,
        request_key: str | None,
    ) -> str:
        record = await self.authorize(organization_id, user_id)
        target = validate_return_url(return_url, self._origins)
        if record.stripe_customer_id is None:
            raise BillingConflict
        return await _stripe_call(
            self._stripe.create_portal_session(
                customer_id=record.stripe_customer_id,
                return_url=target,
                idempotency_key=_key("portal", record.id, request_key),
            )
        )

    async def change_plan(
        self,
        organization_id: str,
        user_id: str,
        *,
        plan: PlanKey,
        interval: str,
        request_key: str | None,
    ) -> None:
        record = await self.authorize(organization_id, user_id)
        subscription_id = record.stripe_subscription_id
        if (
            plan not in PAID_PLANS
            or subscription_id is None
            or not _has_live_subscription(record)
        ):
            raise BillingConflict
        price = self._price(plan, interval)
        current = await _stripe_call(self._stripe.get_subscription(subscription_id))
        if (
            current.customer_id != record.stripe_customer_id
            or current.item_id is None
            or current.price_id == price
        ):
            raise BillingConflict
        await _stripe_call(
            self._stripe.change_subscription_price(
                subscription_id=subscription_id,
                item_id=current.item_id,
                price_id=price,
                idempotency_key=_key("change", record.id, request_key),
            )
        )

    async def set_cancellation(
        self,
        organization_id: str,
        user_id: str,
        *,
        cancel: bool,
        request_key: str | None,
    ) -> None:
        record = await self.authorize(organization_id, user_id)
        subscription_id = record.stripe_subscription_id
        if subscription_id is None or not _has_live_subscription(record):
            raise BillingConflict
        await _stripe_call(
            self._stripe.set_cancel_at_period_end(
                subscription_id=subscription_id,
                cancel=cancel,
                idempotency_key=_key(
                    "cancel" if cancel else "resume", record.id, request_key
                ),
            )
        )

    async def invoices(self, organization_id: str, user_id: str) -> list[StripeInvoice]:
        record = await self.authorize(organization_id, user_id)
        if record.stripe_customer_id is None:
            return []
        return await _stripe_call(self._stripe.list_invoices(record.stripe_customer_id))

    async def payment_methods(
        self, organization_id: str, user_id: str
    ) -> list[StripePaymentMethod]:
        record = await self.authorize(organization_id, user_id)
        if record.stripe_customer_id is None:
            return []
        methods = await _stripe_call(
            self._stripe.list_payment_methods(record.stripe_customer_id)
        )
        default = await _stripe_call(
            self._stripe.get_default_payment_method_id(record.stripe_customer_id)
        )
        return [replace(m, is_default=m.id == default) for m in methods]

    async def delete_payment_method(
        self,
        organization_id: str,
        user_id: str,
        payment_method_id: str,
        *,
        request_key: str,
    ) -> None:
        record = await self.authorize(organization_id, user_id)
        customer_id = await self._owned_customer(record, payment_method_id)
        if _has_live_subscription(record):
            default = await _stripe_call(
                self._stripe.get_default_payment_method_id(customer_id)
            )
            if default == payment_method_id:
                # Removing the card that renews the subscription would make it lapse.
                raise BillingConflict
        await _stripe_call(
            self._stripe.detach_payment_method(
                payment_method_id=payment_method_id,
                idempotency_key=_key("pm-delete", record.id, request_key),
            )
        )

    async def set_default_payment_method(
        self,
        organization_id: str,
        user_id: str,
        payment_method_id: str,
        *,
        request_key: str,
    ) -> None:
        record = await self.authorize(organization_id, user_id)
        customer_id = await self._owned_customer(record, payment_method_id)
        await _stripe_call(
            self._stripe.set_default_payment_method(
                customer_id=customer_id,
                payment_method_id=payment_method_id,
                idempotency_key=_key("pm-default", record.id, request_key),
            )
        )

    async def _owned_customer(
        self, record: OrgBillingRecord, payment_method_id: str
    ) -> str:
        """The organisation's customer id, if it owns the payment method.

        An organisation with no customer, an unknown payment method and another
        customer's payment method all raise the same error.
        """
        customer_id = record.stripe_customer_id
        if customer_id is None:
            raise PaymentMethodNotFound
        try:
            owner = await self._stripe.get_payment_method_customer_id(payment_method_id)
        except StripeNotFound:
            raise PaymentMethodNotFound from None
        except StripeError:
            raise BillingUnavailable from None
        if owner != customer_id:
            raise PaymentMethodNotFound
        return customer_id

    def _interval(self, price_id: str | None) -> str | None:
        """monthly or yearly for a configured price id; None if it is not in the catalogue.

        Rotating a price id in settings leaves subscriptions on the old id unmapped.
        """
        if price_id is None:
            return None
        return next(
            (
                interval
                for (_, interval), id_ in self._prices.items()
                if id_ == price_id
            ),
            None,
        )

    def _price(self, plan: PlanKey, interval: str) -> str:
        price = self._prices.get((plan, interval))
        if price is None:
            raise BillingNotConfigured
        return price

    async def _ensure_customer(self, record: OrgBillingRecord) -> str:
        if record.stripe_customer_id:
            return record.stripe_customer_id
        # Deterministic key: a retry after a failed save gets the same customer back.
        created = await _stripe_call(
            self._stripe.create_customer(
                name=record.name,
                organization_id=record.id,
                idempotency_key=f"sc-customer-{record.id}",
            )
        )
        saved = await self._store.link_customer(record.id, created)
        await self._session.commit()
        return saved
