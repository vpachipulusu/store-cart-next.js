"""Platform-admin subscription management (KAN-48): list, detail, cancel, refund, grant.

Subscription state belongs to the organisation and the Stripe webhook (KAN-44) is its
single writer. Cancel and refund therefore only ask Stripe to act; the webhook records
the outcome. A grant never touches Stripe state: it is stored apart (``granted_plan`` /
``granted_until``) and lifts the plan while it lasts (``effective_plan_key``).

Money-moving calls (cancel, refund) take the caller's ``Idempotency-Key``. No database
transaction, and so no connection, is held while Stripe is called.

* The Stripe key is deterministic (``sc-admin-<operation>:<org>:<key>``), and the audit
  row is found again by a hash of the key, so a retry neither calls Stripe nor audits
  twice once the result is recorded.
* Refund writes a *pending* audit row (committed) before Stripe moves money, then moves
  that same row to completed or failed. The trail therefore never depends on Stripe's
  24 hour key window: a retry of a pending row first looks for a refund that carries
  the request's reference in its metadata, and only creates one if there is none.
* Cancel is decided by Stripe's live subscription state (Stripe ignores idempotency keys
  on DELETE): a subscription already ended or ending is audited without a second call.
* If recording the result fails after Stripe acted, the client gets a 503 and retries
  with the same key; every step above is safe to repeat.
"""

import hashlib
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AdminContext
from app.core.plans import PlanKey, effective_plan_key
from app.core.stripe_admin import StripeAdminBilling, StripeCharge, StripeRefund
from app.core.stripe_billing import StripeError, StripeNotFound, StripeRejected
from app.repositories.admin_subscriptions import (
    RequestRow,
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
REVOKE_GRANT_ACTION = "admin.subscriptions.revoke_grant"
ENDED_STATUSES = frozenset({"canceled", "incomplete_expired"})

logger = logging.getLogger("storecart.admin_subscriptions")


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


class CommitFailed(Exception):
    """The result could not be recorded after (or before) Stripe acted (503, retry)."""


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
    async def clear_grant(self, organization_id: str) -> None: ...
    async def lock_request(self, key: str) -> None: ...
    async def find_request(
        self, action: str, organization_id: str, request_ref: str
    ) -> RequestRow | None: ...
    async def update_request(self, row_id: str, metadata: dict[str, Any]) -> None: ...


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


@dataclass(frozen=True)
class RevokeResult:
    already_applied: bool


def request_ref(request_key: str) -> str:
    """Stable reference to a client key for the audit trail (the key itself is not stored)."""
    return hashlib.sha256(request_key.encode()).hexdigest()


def _stripe_key(operation: str, organization_id: str, request_key: str) -> str:
    return f"sc-admin-{operation}:{organization_id}:{request_key}"


@contextmanager
def _stripe_errors(not_found: type[Exception]) -> Iterator[None]:
    """Turn Stripe failures into this service's errors (no Stripe text survives)."""
    try:
        yield
    except StripeNotFound:
        raise not_found from None
    except StripeRejected:
        raise StripeRefused from None
    except StripeError:
        raise BillingUnavailable from None


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
        record = await self._require(organization_id)
        prior = await self.store.find_request(CANCEL_ACTION, organization_id, ref)
        # No transaction (so no connection) is held while Stripe is called.
        await self.session.rollback()
        if prior is not None:
            return self._replayed_cancel(prior, immediately)
        subscription_id = record.stripe_subscription_id
        if subscription_id is None or record.stripe_customer_id is None:
            raise SubscriptionConflict
        stripe = self._stripe()
        stripe_key = _stripe_key("cancel", organization_id, request_key)
        with _stripe_errors(SubscriptionConflict):
            # Stripe's live state decides, not the local copy the webhook may not have
            # updated yet: this is also what lets a retry after a lost audit row succeed.
            subscription = await stripe.get_subscription(subscription_id)
            if subscription.customer_id != record.stripe_customer_id:
                raise SubscriptionConflict
            ended = (subscription.status or "") in ENDED_STATUSES
            if ended and not immediately:
                raise SubscriptionConflict
            if immediately and not ended:
                await stripe.cancel_subscription(
                    subscription_id, idempotency_key=stripe_key
                )
            elif not immediately and not subscription.cancel_at_period_end:
                await stripe.set_cancel_at_period_end(
                    subscription_id=subscription_id,
                    cancel=True,
                    idempotency_key=stripe_key,
                )
        return await self._record_cancel(actor, record, ref, immediately)

    async def _record_cancel(
        self,
        actor: AdminContext,
        record: SubscriptionRecord,
        ref: str,
        immediately: bool,
    ) -> CancelResult:
        try:
            await self.store.lock_request(f"{CANCEL_ACTION}:{record.id}:{ref}")
            prior = await self.store.find_request(CANCEL_ACTION, record.id, ref)
            if prior is not None:  # a concurrent request with this key finished first
                await self.session.rollback()
                return self._replayed_cancel(prior, immediately)
            await self.auditor.record(
                actor,
                action=CANCEL_ACTION,
                resource="subscriptions",
                resource_id=record.id,
                organization_id=record.id,
                before={
                    "status": record.subscription_status,
                    "plan": record.subscription_tier,
                    "cancel_at_period_end": record.stripe_cancel_at_period_end,
                },
                after={"cancellation": "immediate" if immediately else "period_end"},
                details={"immediately": immediately, "request_ref": ref},
            )
            await self.session.commit()
        except IdempotencyMismatch:
            raise
        except Exception:  # noqa: BLE001 - any recording failure means "retry"; logged by _abandon
            await self._abandon("cancel")
            raise CommitFailed from None
        return CancelResult(immediately, already_applied=False)

    async def refund(
        self,
        actor: AdminContext,
        organization_id: str,
        *,
        charge_id: str,
        amount: int,
        reason: str | None,
        request_key: str,
    ) -> RefundResult:
        """Refund in three steps so the audit trail never depends on Stripe's key window.

        1. A pending audit row is committed *before* Stripe is asked to move money.
        2. Stripe is called without a transaction open; a retry of a pending row first
           looks for a refund carrying this request's reference, so a refund whose
           result was not recorded is found again even after Stripe forgot the key.
        3. The row is updated to completed (or failed) and committed.
        """
        ref = request_ref(request_key)
        record = await self._require(organization_id)
        prior = await self.store.find_request(REFUND_ACTION, organization_id, ref)
        await self.session.rollback()
        done = self._prior_refund(prior, charge_id, amount, reason)
        if done is not None:
            return done
        customer_id = record.stripe_customer_id
        if customer_id is None:
            raise PaymentNotFound
        stripe = self._stripe()
        with _stripe_errors(PaymentNotFound):
            charge = await self._owned_charge(stripe, charge_id, customer_id)
        if prior is None and amount > charge.refundable:
            raise RefundExceedsBalance
        done, resumed = await self._record_refund_intent(
            actor, organization_id, ref, charge, amount, reason
        )
        if done is not None:
            return done
        try:
            with _stripe_errors(PaymentNotFound):
                refund = await stripe.find_refund(charge.id, ref) if resumed else None
                if refund is None:
                    refund = await stripe.create_refund(
                        charge_id=charge.id,
                        amount=amount,
                        reason=reason,
                        organization_id=organization_id,
                        request_ref=ref,
                        idempotency_key=_stripe_key(
                            "refund", organization_id, request_key
                        ),
                    )
        except (PaymentNotFound, StripeRefused, BillingUnavailable) as exc:
            # Only a definite refusal is "failed". After a timeout or 5xx Stripe may
            # already have created the refund, so the row stays pending and a retry
            # looks the refund up by its reference.
            if not isinstance(exc, BillingUnavailable):
                await self._mark_refund_failed(organization_id, ref)
            if isinstance(exc, StripeRefused) and amount > charge.refundable:
                raise RefundExceedsBalance from None
            raise
        return await self._complete_refund(organization_id, ref, charge, refund)

    async def _record_refund_intent(
        self,
        actor: AdminContext,
        organization_id: str,
        ref: str,
        charge: StripeCharge,
        amount: int,
        reason: str | None,
    ) -> tuple[RefundResult | None, bool]:
        """Commit the pending row. Returns (result of a finished twin or None, resumed)."""
        try:
            await self.store.lock_request(f"{REFUND_ACTION}:{organization_id}:{ref}")
            await self.store.lock_request(f"refund-charge:{charge.id}")
            prior = await self.store.find_request(REFUND_ACTION, organization_id, ref)
            done = self._prior_refund(prior, charge.id, amount, reason)
            if done is not None:
                await self.session.rollback()
                return done, True
            if prior is None:
                await self.auditor.record(
                    actor,
                    action=REFUND_ACTION,
                    resource="subscriptions",
                    resource_id=organization_id,
                    organization_id=organization_id,
                    details={
                        "request_ref": ref,
                        "charge_id": charge.id,
                        "amount": amount,
                        "currency": charge.currency,
                        "reason": reason,
                        "state": "pending",
                    },
                )
            else:
                await self._set_state(prior, "pending")
            await self.session.commit()
        except IdempotencyMismatch:
            raise
        except Exception:  # noqa: BLE001 - any recording failure means "retry"; logged by _abandon
            await self._abandon("refund intent")
            raise CommitFailed from None
        return None, prior is not None

    async def _complete_refund(
        self, organization_id: str, ref: str, charge: StripeCharge, refund: StripeRefund
    ) -> RefundResult:
        currency = refund.currency or charge.currency
        try:
            await self.store.lock_request(f"{REFUND_ACTION}:{organization_id}:{ref}")
            row = await self.store.find_request(REFUND_ACTION, organization_id, ref)
            if row is None:
                raise LookupError("refund intent row is missing")
            finished = self._finished_refund(row)
            if finished is not None:  # a concurrent request recorded it first
                await self.session.rollback()
                return finished
            await self._set_state(
                row,
                "completed",
                amount=refund.amount,
                currency=currency,
                refund_id=refund.id,
                refund_status=refund.status,
            )
            await self.session.commit()
        except Exception:  # noqa: BLE001 - any recording failure means "retry"; logged by _abandon
            await self._abandon("refund result")
            raise CommitFailed from None
        return RefundResult(
            refund.id,
            charge.id,
            refund.amount,
            currency,
            refund.status,
            already_applied=False,
        )

    async def _mark_refund_failed(self, organization_id: str, ref: str) -> None:
        """Best effort: record that Stripe refused, so the row is not left 'pending'."""
        try:
            row = await self.store.find_request(REFUND_ACTION, organization_id, ref)
            if row is not None and row.details.get("state") == "pending":
                await self._set_state(row, "failed")
            await self.session.commit()
        except Exception:  # noqa: BLE001 - any recording failure means "retry"; logged by _abandon
            await self._abandon("refund failure mark")

    async def _set_state(self, row: RequestRow, state: str, **changes: Any) -> None:
        details = {**row.details, **changes, "state": state}
        await self.store.update_request(row.id, {**row.metadata, "details": details})

    async def _abandon(self, what: str) -> None:
        logger.exception("admin subscription %s was not recorded", what)
        try:
            await self.session.rollback()
        except Exception:
            logger.exception("rollback failed")

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

    async def revoke_grant(
        self, actor: AdminContext, organization_id: str, *, request_key: str
    ) -> RevokeResult:
        """Clear a granted plan; the organisation falls back to its Stripe-derived plan.

        Same two steps as a refund, minus Stripe: a pending audit row is committed
        before the grant is cleared, then the row moves to completed in the same
        transaction as the change. A retry with the same key resumes a pending row or
        replays a completed one; a replay never clears a newer grant.
        """
        ref = request_ref(request_key)
        record = await self._require(organization_id)
        prior = await self.store.find_request(REVOKE_GRANT_ACTION, organization_id, ref)
        if prior is not None and prior.details.get("state") == "completed":
            await self.session.rollback()
            return RevokeResult(already_applied=True)
        if prior is None and record.granted_plan is None:
            raise SubscriptionConflict
        if prior is None:
            await self._record_revoke_intent(actor, record, ref)
        return await self._complete_revoke(organization_id, ref)

    async def _record_revoke_intent(
        self, actor: AdminContext, record: SubscriptionRecord, ref: str
    ) -> None:
        try:
            await self.store.lock_request(f"{REVOKE_GRANT_ACTION}:{record.id}:{ref}")
            twin = await self.store.find_request(REVOKE_GRANT_ACTION, record.id, ref)
            if twin is None:  # else a concurrent request with this key staged it
                await self.auditor.record(
                    actor,
                    action=REVOKE_GRANT_ACTION,
                    resource="subscriptions",
                    resource_id=record.id,
                    organization_id=record.id,
                    before={
                        "granted_plan": record.granted_plan,
                        "granted_until": record.granted_until,
                    },
                    details={"request_ref": ref, "state": "pending"},
                )
            await self.session.commit()
        except Exception:  # noqa: BLE001 - any recording failure means "retry"; logged by _abandon
            await self._abandon("revoke intent")
            raise CommitFailed from None

    async def _complete_revoke(self, organization_id: str, ref: str) -> RevokeResult:
        try:
            await self.store.lock_request(
                f"{REVOKE_GRANT_ACTION}:{organization_id}:{ref}"
            )
            row = await self.store.find_request(
                REVOKE_GRANT_ACTION, organization_id, ref
            )
            if row is None:
                raise LookupError("revoke intent row is missing")
            if row.details.get("state") == "completed":  # a concurrent twin won
                await self.session.rollback()
                return RevokeResult(already_applied=True)
            await self._require(organization_id, lock=True)
            await self.store.clear_grant(organization_id)
            await self._set_state(row, "completed")
            await self.session.commit()
        except Exception:  # noqa: BLE001 - any recording failure means "retry"; logged by _abandon
            await self._abandon("revoke result")
            raise CommitFailed from None
        return RevokeResult(already_applied=False)

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
            logger.warning(
                "stripe charges unavailable", extra={"organization_id": record.id}
            )
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
    def _replayed_cancel(prior: RequestRow, immediately: bool) -> CancelResult:
        if prior.details.get("immediately") is not immediately:
            raise IdempotencyMismatch
        return CancelResult(immediately, already_applied=True)

    @classmethod
    def _prior_refund(
        cls, prior: RequestRow | None, charge_id: str, amount: int, reason: str | None
    ) -> RefundResult | None:
        """The finished result of an earlier request with this key; None if unfinished."""
        if prior is None:
            return None
        details = prior.details
        if (
            details.get("charge_id") != charge_id
            or details.get("amount") != amount
            or details.get("reason") != reason
        ):
            raise IdempotencyMismatch
        return cls._finished_refund(prior)

    @staticmethod
    def _finished_refund(row: RequestRow) -> RefundResult | None:
        details = row.details
        if details.get("state") != "completed":
            return None
        refund_id = details.get("refund_id")
        charge_id = details.get("charge_id")
        currency = details.get("currency")
        amount = details.get("amount")
        status = details.get("refund_status")
        if not (
            isinstance(refund_id, str)
            and isinstance(charge_id, str)
            and isinstance(currency, str)
            and isinstance(amount, int)
        ):
            raise IdempotencyMismatch  # a damaged row is never replayed as a result
        return RefundResult(
            refund_id,
            charge_id,
            amount,
            currency,
            status if isinstance(status, str) else None,
            already_applied=True,
        )
