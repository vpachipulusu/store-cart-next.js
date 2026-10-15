"""Platform-admin subscription management (KAN-48): list, detail, cancel, refund, grant.

Subscription state belongs to the organisation and the Stripe webhook (KAN-44) is its
single writer. Cancel and refund therefore only ask Stripe to act; the webhook records
the outcome. A grant never touches Stripe state: it is stored apart (``granted_plan`` /
``granted_until``) and lifts the plan while it lasts (``effective_plan_key``).

Money-moving calls (cancel, refund) take the caller's ``Idempotency-Key``:

* the Stripe key is deterministic (``sc-admin-<operation>-<org>-<key>``), so a retry
  reaches Stripe as the same request;
* an advisory lock serialises requests with the same key, and the audit row (found by
  a hash of the key) tells a retry the work is already done, so it neither calls Stripe
  again nor writes a second audit row;
* the audit row is staged after Stripe accepted and committed once. If that commit
  fails the client retries with the same key: Stripe replays its answer and the audit
  row is written then.

Every change writes exactly one audit entry in the caller's transaction (see
``app.services.audit``); a refusal raises before any commit.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AdminContext
from app.core.plans import PlanKey, effective_plan_key
from app.core.stripe_admin import StripeAdminBilling, StripeCharge
from app.core.stripe_billing import StripeError, StripeNotFound, StripeRejected
from app.repositories.admin_subscriptions import (
    SubscriptionFilters,
    SubscriptionPage,
    SubscriptionRecord,
)
from app.services.org_billing import PAYING_STATUSES

MAX_PAGE_SIZE = 100
MAX_GRANT_DAYS = 730
GRANTABLE_PLANS = frozenset({PlanKey.PRO, PlanKey.ENTERPRISE})

CANCEL_ACTION = "admin.subscriptions.cancel"
REFUND_ACTION = "admin.subscriptions.refund"
GRANT_ACTION = "admin.subscriptions.grant"


class SubscriptionNotFound(Exception):
    """No such organisation (404)."""


class PaymentNotFound(Exception):
    """No such charge on this organisation's customer (404).

    Raised for an unknown charge and for another customer's charge alike.
    """


class SubscriptionConflict(Exception):
    """The request does not fit the organisation's current state (409)."""


class RefundExceedsBalance(Exception):
    """The amount is more than what is left to refund on the charge (409)."""


class IdempotencyMismatch(Exception):
    """The Idempotency-Key was used before for a different request (409)."""


class StripeRefused(Exception):
    """Stripe refused the request itself (409)."""


class BillingUnavailable(Exception):
    """A Stripe call failed (502)."""


class BillingNotConfigured(Exception):
    """No Stripe secret key is configured (503)."""


class InvalidGrant(Exception):
    """The grant plan or expiry is not allowed (422)."""


class SubscriptionsStore(Protocol):
    async def list_subscriptions(
        self, filters: SubscriptionFilters, now: datetime, limit: int, offset: int
    ) -> SubscriptionPage: ...
    async def get(
        self, organization_id: str, *, lock: bool = False
    ) -> SubscriptionRecord | None: ...
    async def set_grant(
        self, organization_id: str, plan: str, until: datetime
    ) -> None: ...
    async def lock_request(self, key: str) -> None: ...
    async def find_request_details(
        self, action: str, organization_id: str, request_ref: str
    ) -> dict[str, Any] | None: ...


class AuditRecorder(Protocol):
    async def record(
        self,
        admin: AdminContext,
        *,
        action: str,
        resource: str,
        resource_id: str | None = None,
        organization_id: str | None = None,
        store_id: str | None = None,
        before: object = None,
        after: object = None,
        details: object = None,
    ) -> None: ...


@dataclass(frozen=True)
class SubscriptionDetail:
    record: SubscriptionRecord
    # None when Stripe is not configured or unreachable; [] when there are no charges.
    payments: list[StripeCharge] | None


@dataclass(frozen=True)
class CancelResult:
    immediately: bool
    already_applied: bool


@dataclass(frozen=True)
class RefundResult:
    refund_id: str
    charge_id: str
    amount: int
    currency: str
    status: str | None
    already_applied: bool


@dataclass(frozen=True)
class GrantResult:
    granted_plan: str
    granted_until: datetime
    changed: bool


def request_ref(request_key: str) -> str:
    """Stable reference to a client key for the audit trail (the key itself is not stored)."""
    return hashlib.sha256(request_key.encode()).hexdigest()


def _stripe_key(operation: str, organization_id: str, request_key: str) -> str:
    return f"sc-admin-{operation}-{organization_id}-{request_key}"


def _has_live_subscription(record: SubscriptionRecord) -> bool:
    return (
        record.stripe_subscription_id is not None
        and record.subscription_status in PAYING_STATUSES
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AdminSubscriptionsService:
    def __init__(
        self,
        store: SubscriptionsStore,
        session: AsyncSession,
        stripe: StripeAdminBilling | None,
        auditor: AuditRecorder,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store, self.session = store, session
        self.stripe, self.auditor, self.clock = stripe, auditor, clock

    async def list_subscriptions(
        self, filters: SubscriptionFilters, limit: int, offset: int
    ) -> SubscriptionPage:
        return await self.store.list_subscriptions(
            filters, self.clock(), min(max(limit, 1), MAX_PAGE_SIZE), max(offset, 0)
        )

    def plan_of(self, record: SubscriptionRecord) -> PlanKey:
        return effective_plan_key(
            record.subscription_tier,
            record.granted_plan,
            record.granted_until,
            self.clock(),
        )

    async def get_detail(self, organization_id: str) -> SubscriptionDetail:
        record = await self.store.get(organization_id)
        if record is None:
            raise SubscriptionNotFound
        # End the read transaction so no connection is held during the Stripe call.
        await self.session.rollback()
        return SubscriptionDetail(record, await self._payments(record))

    async def cancel(
        self,
        actor: AdminContext,
        organization_id: str,
        *,
        immediately: bool,
        request_key: str,
    ) -> CancelResult:
        ref = request_ref(request_key)
        await self.store.lock_request(f"{CANCEL_ACTION}:{organization_id}:{ref}")
        record = await self._require(organization_id)
        prior = await self.store.find_request_details(
            CANCEL_ACTION, organization_id, ref
        )
        if prior is not None:
            if prior.get("immediately") is not immediately:
                raise IdempotencyMismatch
            return CancelResult(immediately, already_applied=True)
        subscription_id = record.stripe_subscription_id
        if subscription_id is None or not _has_live_subscription(record):
            raise SubscriptionConflict
        if not immediately and record.stripe_cancel_at_period_end:
            raise SubscriptionConflict
        stripe = self._stripe()
        stripe_key = _stripe_key("cancel", organization_id, request_key)
        try:
            subscription = await stripe.get_subscription(subscription_id)
            if subscription.customer_id != record.stripe_customer_id:
                raise SubscriptionConflict
            if immediately:
                await stripe.cancel_subscription(
                    subscription_id, idempotency_key=stripe_key
                )
            else:
                await stripe.set_cancel_at_period_end(
                    subscription_id=subscription_id,
                    cancel=True,
                    idempotency_key=stripe_key,
                )
        except StripeRejected:
            raise StripeRefused from None
        except StripeError:
            raise BillingUnavailable from None
        await self.auditor.record(
            actor,
            action=CANCEL_ACTION,
            resource="subscriptions",
            resource_id=organization_id,
            organization_id=organization_id,
            before={
                "status": record.subscription_status,
                "plan": record.subscription_tier,
                "cancel_at_period_end": record.stripe_cancel_at_period_end,
            },
            after={"cancellation": "immediate" if immediately else "period_end"},
            details={"immediately": immediately, "request_ref": ref},
        )
        await self.session.commit()
        return CancelResult(immediately, already_applied=False)

    async def refund(
        self,
        actor: AdminContext,
        organization_id: str,
        *,
        charge_id: str,
        amount: int | None,
        reason: str | None,
        request_key: str,
    ) -> RefundResult:
        ref = request_ref(request_key)
        await self.store.lock_request(f"{REFUND_ACTION}:{organization_id}:{ref}")
        record = await self._require(organization_id)
        prior = await self.store.find_request_details(
            REFUND_ACTION, organization_id, ref
        )
        if prior is not None:
            return self._replayed_refund(prior, charge_id, amount)
        customer_id = record.stripe_customer_id
        if customer_id is None:
            raise PaymentNotFound
        stripe = self._stripe()
        try:
            charge = await self._owned_charge(stripe, charge_id, customer_id)
            refundable = charge.refundable
            if refundable <= 0:
                raise SubscriptionConflict
            wanted = refundable if amount is None else amount
            if wanted > refundable:
                raise RefundExceedsBalance
            refund = await stripe.create_refund(
                charge_id=charge.id,
                amount=wanted,
                reason=reason,
                organization_id=organization_id,
                idempotency_key=_stripe_key("refund", organization_id, request_key),
            )
        except StripeNotFound:
            raise PaymentNotFound from None
        except StripeRejected:
            raise StripeRefused from None
        except StripeError:
            raise BillingUnavailable from None
        currency = refund.currency or charge.currency
        await self.auditor.record(
            actor,
            action=REFUND_ACTION,
            resource="subscriptions",
            resource_id=organization_id,
            organization_id=organization_id,
            details={
                "request_ref": ref,
                "charge_id": charge.id,
                "requested_amount": amount,
                "amount": refund.amount,
                "currency": currency,
                "refund_id": refund.id,
                "refund_status": refund.status,
                "reason": reason,
            },
        )
        await self.session.commit()
        return RefundResult(
            refund.id,
            charge.id,
            refund.amount,
            currency,
            refund.status,
            already_applied=False,
        )

    async def grant(
        self,
        actor: AdminContext,
        organization_id: str,
        *,
        plan: PlanKey,
        until: datetime,
    ) -> GrantResult:
        now = self.clock()
        until = until.astimezone(UTC)
        if (
            plan not in GRANTABLE_PLANS
            or until <= now
            or until > now + timedelta(days=MAX_GRANT_DAYS)
        ):
            raise InvalidGrant
        record = await self._require(organization_id, lock=True)
        if _has_live_subscription(record):
            # A live Stripe subscription already gives the plan; a grant beside it
            # would only contradict it.
            raise SubscriptionConflict
        if record.granted_plan == plan.value and record.granted_until == until:
            return GrantResult(plan.value, until, changed=False)
        await self.store.set_grant(organization_id, plan.value, until)
        await self.auditor.record(
            actor,
            action=GRANT_ACTION,
            resource="subscriptions",
            resource_id=organization_id,
            organization_id=organization_id,
            before={
                "granted_plan": record.granted_plan,
                "granted_until": record.granted_until,
            },
            after={"granted_plan": plan.value, "granted_until": until},
        )
        await self.session.commit()
        return GrantResult(plan.value, until, changed=True)

    async def _require(
        self, organization_id: str, *, lock: bool = False
    ) -> SubscriptionRecord:
        record = await self.store.get(organization_id, lock=lock)
        if record is None:
            raise SubscriptionNotFound
        return record

    def _stripe(self) -> StripeAdminBilling:
        if self.stripe is None:
            raise BillingNotConfigured
        return self.stripe

    async def _payments(self, record: SubscriptionRecord) -> list[StripeCharge] | None:
        if record.stripe_customer_id is None:
            return []
        if self.stripe is None:
            return None
        try:
            return await self.stripe.list_charges(record.stripe_customer_id)
        except StripeError:
            return None

    @staticmethod
    async def _owned_charge(
        stripe: StripeAdminBilling, charge_id: str, customer_id: str
    ) -> StripeCharge:
        charge = await stripe.get_charge(charge_id)
        if charge.customer_id != customer_id:
            raise PaymentNotFound
        return charge

    @staticmethod
    def _replayed_refund(
        prior: dict[str, Any], charge_id: str, amount: int | None
    ) -> RefundResult:
        if (
            prior.get("charge_id") != charge_id
            or prior.get("requested_amount") != amount
        ):
            raise IdempotencyMismatch
        return RefundResult(
            refund_id=str(prior.get("refund_id")),
            charge_id=charge_id,
            amount=int(prior.get("amount") or 0),
            currency=str(prior.get("currency") or ""),
            status=prior.get("refund_status"),
            already_applied=True,
        )
