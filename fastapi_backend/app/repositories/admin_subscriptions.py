"""Queries behind the admin subscriptions API (KAN-48).

Reads organisations and their audit rows; the only organisation write is the admin
grant (``set_grant``). Subscription state that comes from Stripe is never written here.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, or_, select, update
from sqlalchemy.orm import QueryableAttribute

from app.core.plans import PlanKey
from app.models.platform.audit_log import AuditLog
from app.models.platform.organization import Organization
from app.repositories.base import BaseRepository

_RANKS = {PlanKey.FREE: 0, PlanKey.PRO: 1, PlanKey.ENTERPRISE: 2}


@dataclass(frozen=True)
class SubscriptionRecord:
    id: str
    name: str
    slug: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_current_period_end: datetime | None
    subscription_tier: str
    subscription_status: str
    stripe_cancel_at_period_end: bool
    granted_plan: str | None
    granted_until: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RequestRow:
    """The audit row of an earlier cancel or refund request (found by its key hash)."""

    id: str
    metadata: dict[str, Any]

    @property
    def details(self) -> dict[str, Any]:
        found = self.metadata.get("details")
        return found if isinstance(found, dict) else {}


@dataclass(frozen=True)
class SubscriptionFilters:
    status: str | None = None
    plan: PlanKey | None = None


@dataclass(frozen=True)
class SubscriptionPage:
    items: list[SubscriptionRecord]
    total_count: int


def _record(row: Organization) -> SubscriptionRecord:
    return SubscriptionRecord(
        id=row.id,
        name=row.name,
        slug=row.slug,
        stripe_customer_id=row.stripe_customer_id,
        stripe_subscription_id=row.stripe_subscription_id,
        stripe_current_period_end=row.stripe_current_period_end,
        subscription_tier=row.subscription_tier,
        subscription_status=row.subscription_status,
        stripe_cancel_at_period_end=row.stripe_cancel_at_period_end,
        granted_plan=row.granted_plan,
        granted_until=row.granted_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _rank(column: QueryableAttribute[Any]) -> ColumnElement[int]:
    return case(
        (column == PlanKey.ENTERPRISE.value, _RANKS[PlanKey.ENTERPRISE]),
        (column == PlanKey.PRO.value, _RANKS[PlanKey.PRO]),
        else_=_RANKS[PlanKey.FREE],
    )


def _grant_active(now: datetime) -> ColumnElement[bool]:
    return and_(
        Organization.granted_plan.is_not(None), Organization.granted_until > now
    )


def _effective_rank(now: datetime) -> ColumnElement[int]:
    """SQL twin of ``app.core.plans.effective_plan_key`` (the e2e tests keep them equal)."""
    stripe_rank = _rank(Organization.subscription_tier)
    granted_rank = _rank(Organization.granted_plan)
    return case(
        (and_(_grant_active(now), granted_rank > stripe_rank), granted_rank),
        else_=stripe_rank,
    )


class AdminSubscriptionsRepository(BaseRepository):
    async def list_subscriptions(
        self, filters: SubscriptionFilters, now: datetime, limit: int, offset: int
    ) -> SubscriptionPage:
        """Organisations that have or had a subscription, or hold a live grant.

        Newest first, with the id as tie-break, so paging is stable.
        """
        conditions: list[ColumnElement[bool]] = [
            or_(
                Organization.stripe_subscription_id.is_not(None),
                _grant_active(now),
                Organization.subscription_tier != PlanKey.FREE.value,
            )
        ]
        if filters.status is not None:
            conditions.append(Organization.subscription_status == filters.status)
        if filters.plan is not None:
            conditions.append(_effective_rank(now) == _RANKS[filters.plan])
        total = await self._session.scalar(
            select(func.count()).select_from(Organization).where(*conditions)
        )
        rows = await self._session.scalars(
            select(Organization)
            .where(*conditions)
            .order_by(Organization.created_at.desc(), Organization.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return SubscriptionPage([_record(row) for row in rows], total or 0)

    async def get(
        self, organization_id: str, *, lock: bool = False
    ) -> SubscriptionRecord | None:
        statement = select(Organization).where(Organization.id == organization_id)
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return _record(row) if row is not None else None

    async def set_grant(self, organization_id: str, plan: str, until: datetime) -> None:
        await self._session.execute(
            update(Organization)
            .where(Organization.id == organization_id)
            .values(granted_plan=plan, granted_until=until)
        )

    async def lock_request(self, key: str) -> None:
        """Serialise requests that share ``key`` until the transaction ends.

        An advisory lock, not a row lock, so a slow Stripe call never blocks the
        Stripe webhook on the organisation row.
        """
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
        )

    async def find_request(
        self, action: str, organization_id: str, request_ref: str
    ) -> RequestRow | None:
        """The audit row of an earlier request with the same reference, if any."""
        details = AuditLog.metadata_["details"]
        row = (
            await self._session.execute(
                select(AuditLog.id, AuditLog.metadata_)
                .where(
                    AuditLog.action == action,
                    AuditLog.organization_id == organization_id,
                    details["request_ref"].as_string() == request_ref,
                )
                .order_by(AuditLog.created_at, AuditLog.id)
                .limit(1)
            )
        ).first()
        if row is None or not isinstance(row[1], dict):
            return None
        return RequestRow(row[0], row[1])

    async def update_request(self, row_id: str, metadata: dict[str, Any]) -> None:
        """Move a refund intent row from pending to completed or failed.

        The only update of an audit row: it rewrites the ``details`` of the row this
        service itself staged before calling Stripe, never anyone else's.
        """
        await self._session.execute(
            update(AuditLog).where(AuditLog.id == row_id).values(metadata_=metadata)
        )
