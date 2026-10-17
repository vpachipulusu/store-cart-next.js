"""Bulk Stripe subscription reconciliation for platform admins (KAN-119).

Reads every Stripe subscription (one paginated call per hundred, never one per
customer) and compares it with the organisations' stored billing state. It reports
drift and writes nothing but one audit row: the Stripe webhook (KAN-44) stays the single
writer of subscription state, so a sync can never overwrite newer webhook data with an
older read. An admin fixes a reported organisation by replaying the Stripe event.

The read transaction opened by the admin check is ended before Stripe is called, so no
connection is held during the Stripe calls. Report size is bounded: at most ``MAX_PAGES`` Stripe pages, and at most
``MAX_DRIFTS`` drift items in the response (the counts are always complete for what
was read; ``truncated`` says the read stopped at the page cap).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AdminContext
from app.core.plans import PlanKey
from app.core.stripe_billing import StripeError
from app.core.stripe_sync import (
    StripeSubscriptionLister,
    StripeSubscriptionSnapshot,
)
from app.repositories.admin_analytics import LinkedOrganization

MAX_PAGES = 20
MAX_DRIFTS = 100
MAX_BILLED_LOOKUP = 10_000
SYNC_ACTION = "admin.subscriptions.sync"
# Mirrors the webhook: these statuses keep the plan, these end it.
ENTITLED = frozenset({"active", "trialing", "past_due"})
ENDED = frozenset({"canceled", "unpaid", "incomplete_expired", "paused"})
BILLED = frozenset({"active", "trialing", "past_due", "unpaid", "incomplete", "paused"})

DriftKind = Literal[
    "unmatched",
    "subscription_id",
    "status",
    "plan",
    "cancel_at_period_end",
    "missing_in_stripe",
]

logger = logging.getLogger("storecart.admin_subscription_sync")


class SyncNotConfigured(Exception):
    """No Stripe secret key is configured (503)."""


class SyncUnavailable(Exception):
    """A Stripe call failed (502)."""


@dataclass(frozen=True)
class Drift:
    kind: DriftKind
    organization_id: str | None
    subscription_id: str | None
    stripe_status: str | None
    local_status: str | None


@dataclass(frozen=True)
class SyncReport:
    stripe_subscriptions: int
    in_sync: int
    drift_count: int
    historical_ignored: int
    truncated: bool
    drifts: list[Drift]


class SyncStore(Protocol):
    async def organizations_for_stripe(
        self, subscription_ids: list[str], customer_ids: list[str]
    ) -> list[LinkedOrganization]: ...
    async def billed_subscriptions(
        self, statuses: frozenset[str], limit: int
    ) -> list[LinkedOrganization]: ...


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


def _expected_tier(
    stripe: StripeSubscriptionSnapshot, prices: Mapping[str, PlanKey]
) -> str | None:
    """The tier the webhook would store; None when the price is not in the catalogue."""
    if stripe.status in ENDED:
        return PlanKey.FREE.value
    if stripe.status not in ENTITLED:
        return None  # incomplete: the webhook keeps the current tier
    plan = prices.get(stripe.price_id) if stripe.price_id else None
    return plan.value if plan else None


def compare(
    stripe: StripeSubscriptionSnapshot,
    org: LinkedOrganization,
    prices: Mapping[str, PlanKey],
) -> DriftKind | None:
    """The first way the stored state differs from Stripe's, or None when in sync."""
    if org.stripe_subscription_id != stripe.id:
        return "subscription_id"
    if org.subscription_status != stripe.status:
        return "status"
    expected = _expected_tier(stripe, prices)
    if expected is not None and org.subscription_tier != expected:
        return "plan"
    if (
        stripe.status not in ENDED
        and org.stripe_cancel_at_period_end != stripe.cancel_at_period_end
    ):
        return "cancel_at_period_end"
    return None


class SubscriptionSyncService:
    def __init__(
        self,
        store: SyncStore,
        session: AsyncSession,
        lister: StripeSubscriptionLister | None,
        auditor: AuditRecorder,
        prices: Mapping[str, PlanKey],
    ) -> None:
        self.store, self.session, self.lister = store, session, lister
        self.auditor, self.prices = auditor, prices

    async def reconcile(self, actor: AdminContext) -> SyncReport:
        if self.lister is None:
            raise SyncNotConfigured
        await self.session.rollback()
        try:
            snapshots, truncated = await self._read_stripe(self.lister)
        except SyncUnavailable:
            await self._audit(actor, {"outcome": "unavailable"})
            raise
        report = await self._compare(snapshots, truncated)
        await self._audit(
            actor,
            {
                "outcome": "completed",
                "stripe_subscriptions": report.stripe_subscriptions,
                "in_sync": report.in_sync,
                "drift_count": report.drift_count,
                "truncated": report.truncated,
            },
        )
        return report

    async def _audit(self, actor: AdminContext, details: dict[str, object]) -> None:
        await self.auditor.record(
            actor, action=SYNC_ACTION, resource="subscriptions", details=details
        )
        await self.session.commit()

    @staticmethod
    async def _read_stripe(
        lister: StripeSubscriptionLister,
    ) -> tuple[list[StripeSubscriptionSnapshot], bool]:
        snapshots: list[StripeSubscriptionSnapshot] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            try:
                page = await lister.list_subscriptions(cursor)
            except StripeError:
                raise SyncUnavailable from None
            snapshots.extend(page.items)
            if not page.has_more:
                return snapshots, False
            cursor = page.cursor
        return snapshots, True

    async def _compare(
        self, snapshots: list[StripeSubscriptionSnapshot], truncated: bool
    ) -> SyncReport:
        orgs = await self.store.organizations_for_stripe(
            [s.id for s in snapshots],
            [s.customer_id for s in snapshots if s.customer_id],
        )
        by_sub = {o.stripe_subscription_id: o for o in orgs if o.stripe_subscription_id}
        by_customer = {o.stripe_customer_id: o for o in orgs if o.stripe_customer_id}
        drifts: list[Drift] = []
        in_sync = historical = drift_count = 0
        for snap in snapshots:
            org = by_sub.get(snap.id) or by_customer.get(snap.customer_id or "")
            if org is None:
                kind: DriftKind | None = "unmatched"
            elif org.stripe_subscription_id != snap.id and snap.status in ENDED:
                historical += 1  # an old, ended subscription of a customer who moved on
                continue
            else:
                kind = compare(snap, org, self.prices)
            if kind is None:
                in_sync += 1
                continue
            drift_count += 1
            if len(drifts) < MAX_DRIFTS:
                drifts.append(
                    Drift(
                        kind,
                        org.id if org else None,
                        snap.id,
                        snap.status,
                        org.subscription_status if org else None,
                    )
                )
        if not truncated:
            seen = {s.id for s in snapshots}
            billed = await self.store.billed_subscriptions(
                BILLED, MAX_BILLED_LOOKUP + 1
            )
            if len(billed) > MAX_BILLED_LOOKUP:
                truncated = True  # too many local subscriptions to check them all
                billed = billed[:MAX_BILLED_LOOKUP]
            missing = [o for o in billed if o.stripe_subscription_id not in seen]
            drift_count += len(missing)
            for org in missing[: max(MAX_DRIFTS - len(drifts), 0)]:
                drifts.append(
                    Drift(
                        "missing_in_stripe",
                        org.id,
                        org.stripe_subscription_id,
                        None,
                        org.subscription_status,
                    )
                )
        logger.info("subscription sync read %d subscriptions", len(snapshots))
        return SyncReport(
            len(snapshots), in_sync, drift_count, historical, truncated, drifts
        )
