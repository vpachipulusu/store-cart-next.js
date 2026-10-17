"""Read-only aggregate queries behind the platform admin analytics (KAN-119).

Counts and groupings only: nothing here returns a row of personal data, and nothing
writes. Revenue is derived from the organisations' own billing columns, grouped by
price id, so it never costs one Stripe call per customer.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models.platform.admin_user import AdminUser
from app.models.platform.app_setting import AppSetting
from app.models.platform.audit_log import AuditLog
from app.models.platform.email_template import EmailTemplate
from app.models.platform.feature_flag import FeatureFlag
from app.models.platform.organization import Organization
from app.models.platform.seo_meta import SeoMeta
from app.models.platform.store import Store
from app.models.platform.stripe_event import StripeEvent
from app.models.platform.url_redirect import UrlRedirect
from app.models.platform.user import User
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class OverviewCounts:
    users_total: int
    users_verified: int
    users_new: int
    users_active: int
    admins: int
    organizations_total: int
    organizations_new: int
    stores_by_status: dict[str, int]


@dataclass(frozen=True)
class PriceGroup:
    """Billed organisations that share a Stripe price id (None: no price recorded)."""

    price_id: str | None
    count: int


@dataclass(frozen=True)
class SubscriptionBreakdown:
    by_status: dict[str, int]
    by_tier: dict[str, int]
    canceling: int
    active_grants: int


@dataclass(frozen=True)
class SystemCounts:
    app_settings: int
    feature_flags: int
    email_templates: int
    seo_entries: int
    redirects: int
    audit_logs: int
    stripe_events: int
    admin_users: int


@dataclass(frozen=True)
class LinkedOrganization:
    """An organisation as reconciliation sees it."""

    id: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    subscription_tier: str
    subscription_status: str
    stripe_cancel_at_period_end: bool


def _total(table: Any) -> Any:
    return select(func.count()).select_from(table).scalar_subquery()


def _linked(row: Organization) -> LinkedOrganization:
    return LinkedOrganization(
        id=row.id,
        stripe_customer_id=row.stripe_customer_id,
        stripe_subscription_id=row.stripe_subscription_id,
        subscription_tier=row.subscription_tier,
        subscription_status=row.subscription_status,
        stripe_cancel_at_period_end=row.stripe_cancel_at_period_end,
    )


class AdminAnalyticsRepository(BaseRepository):
    async def overview(self, since: datetime, active_since: datetime) -> OverviewCounts:
        users = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count().filter(User.email_verified.is_(True)),
                    func.count().filter(User.created_at >= since),
                    func.count().filter(User.last_login_at >= active_since),
                    _total(AdminUser),
                )
            )
        ).one()
        orgs = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count().filter(Organization.created_at >= since),
                )
            )
        ).one()
        stores = await self._session.execute(
            select(Store.status, func.count()).group_by(Store.status)
        )
        return OverviewCounts(
            users_total=users[0],
            users_verified=users[1],
            users_new=users[2],
            users_active=users[3],
            admins=users[4],
            organizations_total=orgs[0],
            organizations_new=orgs[1],
            stores_by_status={
                getattr(status, "value", str(status)): n for status, n in stores.all()
            },
        )

    async def billed_price_groups(self, statuses: frozenset[str]) -> list[PriceGroup]:
        """Organisations in a billed status, grouped by recorded price id."""
        rows = await self._session.execute(
            select(Organization.stripe_price_id, func.count())
            .where(Organization.subscription_status.in_(statuses))
            .group_by(Organization.stripe_price_id)
        )
        return [PriceGroup(price_id, n) for price_id, n in rows.all()]

    async def subscription_breakdown(self, now: datetime) -> SubscriptionBreakdown:
        by_status = await self._session.execute(
            select(Organization.subscription_status, func.count()).group_by(
                Organization.subscription_status
            )
        )
        by_tier = await self._session.execute(
            select(Organization.subscription_tier, func.count()).group_by(
                Organization.subscription_tier
            )
        )
        extras = (
            await self._session.execute(
                select(
                    func.count().filter(
                        Organization.stripe_cancel_at_period_end.is_(True)
                    ),
                    func.count().filter(
                        Organization.granted_plan.is_not(None),
                        Organization.granted_until > now,
                    ),
                )
            )
        ).one()
        return SubscriptionBreakdown(
            dict(by_status.all()), dict(by_tier.all()), extras[0], extras[1]
        )

    async def system_counts(self) -> SystemCounts:
        row = (
            await self._session.execute(
                select(
                    _total(AppSetting),
                    _total(FeatureFlag),
                    _total(EmailTemplate),
                    _total(SeoMeta),
                    _total(UrlRedirect),
                    _total(AuditLog),
                    _total(StripeEvent),
                    _total(AdminUser),
                )
            )
        ).one()
        return SystemCounts(*(int(value) for value in row))

    async def organizations_for_stripe(
        self, subscription_ids: list[str], customer_ids: list[str]
    ) -> list[LinkedOrganization]:
        """Organisations linked to any of these Stripe subscriptions or customers."""
        rows = await self._session.scalars(
            select(Organization).where(
                Organization.stripe_subscription_id.in_(subscription_ids)
                | Organization.stripe_customer_id.in_(customer_ids)
            )
        )
        return [_linked(row) for row in rows]

    async def billed_subscriptions(
        self, statuses: frozenset[str], limit: int
    ) -> list[LinkedOrganization]:
        """Organisations that claim a live subscription (newest first, bounded)."""
        rows = await self._session.scalars(
            select(Organization)
            .where(
                Organization.stripe_subscription_id.is_not(None),
                Organization.subscription_status.in_(statuses),
            )
            .order_by(Organization.created_at.desc(), Organization.id.desc())
            .limit(limit)
        )
        return [_linked(row) for row in rows]
