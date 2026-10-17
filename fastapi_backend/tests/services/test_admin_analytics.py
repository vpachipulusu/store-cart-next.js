"""Admin analytics and Stripe subscription sync services (KAN-119), with in-memory fakes."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.permissions import AdminContext
from app.core.plans import PlanKey
from app.repositories.admin_analytics import (
    LinkedOrganization,
    OverviewCounts,
    PriceGroup,
    SubscriptionBreakdown,
    SystemCounts,
)
from app.services.admin_analytics import AdminAnalyticsService, PriceEntry
from app.services.admin_subscription_sync import (
    MAX_DRIFTS,
    MAX_PAGES,
    SubscriptionSyncService,
    SyncNotConfigured,
    SyncUnavailable,
)
from tests.fakes_admin_analytics import FakeLister, FakePrices, snapshot

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
CATALOGUE = {
    "price_pro_m": PriceEntry(PlanKey.PRO, "month"),
    "price_pro_y": PriceEntry(PlanKey.PRO, "year"),
    "price_ent_m": PriceEntry(PlanKey.ENTERPRISE, "month"),
}
PLANS = {price: entry.plan for price, entry in CATALOGUE.items()}
BREAKDOWN = SubscriptionBreakdown({"active": 3}, {"pro": 3}, 1, 2)


class FakeAnalyticsStore:
    def __init__(self, groups: list[PriceGroup]) -> None:
        self.groups = groups
        self.windows: list[tuple[datetime, datetime]] = []

    async def overview(self, since: datetime, active_since: datetime) -> OverviewCounts:
        self.windows.append((since, active_since))
        return OverviewCounts(5, 4, 1, 3, 2, 6, 1, {"ACTIVE": 2})

    async def billed_price_groups(self, statuses: frozenset[str]) -> list[PriceGroup]:
        assert statuses == frozenset({"active", "past_due"})
        return self.groups

    async def subscription_breakdown(self, now: datetime) -> SubscriptionBreakdown:
        return BREAKDOWN

    async def system_counts(self) -> SystemCounts:
        return SystemCounts(1, 2, 3, 4, 5, 6, 7, 8)


class Currency:
    async def currency(self) -> str:
        return "GBP"


def analytics(
    groups: list[PriceGroup], prices: FakePrices | None
) -> tuple[AdminAnalyticsService, FakeAnalyticsStore]:
    store = FakeAnalyticsStore(groups)
    return (
        AdminAnalyticsService(store, prices, CATALOGUE, Currency(), lambda: NOW),
        store,
    )


async def test_overview_uses_month_start_and_a_30_day_activity_window():
    service, store = analytics([], None)

    counts = await service.overview()

    assert counts.users_total == 5
    since, active_since = store.windows[0]
    assert since == datetime(2026, 10, 1, tzinfo=UTC)
    assert active_since == datetime(2026, 9, 17, 12, tzinfo=UTC)


async def test_system_returns_the_stores_counts():
    service, _ = analytics([], None)

    assert (await service.system()).audit_logs == 6


async def test_revenue_prices_each_price_id_once_not_once_per_customer():
    prices = FakePrices({"price_pro_m": 2900, "price_ent_m": 9900})
    groups = [PriceGroup("price_pro_m", 40), PriceGroup("price_ent_m", 2)]
    service, _ = analytics(groups, prices)

    report = await service.revenue()

    assert prices.calls == ["price_ent_m", "price_pro_m"]
    assert report.mrr_minor == 40 * 2900 + 2 * 9900
    assert report.arr_minor == report.mrr_minor * 12
    assert report.currency == "GBP"
    assert report.complete
    assert [(p.plan, p.organizations) for p in report.by_plan] == [
        (PlanKey.PRO, 40),
        (PlanKey.ENTERPRISE, 2),
    ]
    assert report.breakdown is BREAKDOWN


async def test_yearly_prices_count_as_one_twelfth_per_month():
    service, _ = analytics(
        [PriceGroup("price_pro_y", 3)], FakePrices({"price_pro_y": 24000})
    )

    assert (await service.revenue()).mrr_minor == 6000


@pytest.mark.parametrize(
    ("price_id", "prices"),
    [
        ("price_unknown", FakePrices({})),  # not in the catalogue
        (None, FakePrices({})),  # billed with no price recorded
        ("price_pro_m", FakePrices({})),  # Stripe cannot read the price
        ("price_pro_m", FakePrices({"price_pro_m": None})),  # price has no unit amount
        ("price_pro_m", None),  # Stripe is not configured
    ],
)
async def test_unpriced_organisations_make_the_report_incomplete(price_id, prices):
    service, _ = analytics([PriceGroup(price_id, 2)], prices)

    report = await service.revenue()

    assert report.unpriced_organizations == 2
    assert not report.complete
    assert report.mrr_minor == 0 and report.by_plan == []


# ------------------------------------------------------------------- sync


def org(**overrides: Any) -> LinkedOrganization:
    base = LinkedOrganization("org1", "cus_1", "sub_1", "pro", "active", False)
    return LinkedOrganization(**{**base.__dict__, **overrides})


class FakeSyncStore:
    def __init__(self, *orgs: LinkedOrganization) -> None:
        self.orgs = list(orgs)

    async def organizations_for_stripe(
        self, subscription_ids: list[str], customer_ids: list[str]
    ) -> list[LinkedOrganization]:
        return [
            o
            for o in self.orgs
            if o.stripe_subscription_id in subscription_ids
            or o.stripe_customer_id in customer_ids
        ]

    async def billed_subscriptions(
        self, statuses: frozenset[str], limit: int
    ) -> list[LinkedOrganization]:
        return [
            o
            for o in self.orgs
            if o.stripe_subscription_id and o.subscription_status in statuses
        ]


class Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class Auditor:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def record(self, admin: AdminContext, **fields: Any) -> None:
        self.rows.append(fields)


ADMIN = AdminContext("u1", "admin", frozenset({"subscriptions.sync"}))


def syncer(
    lister: FakeLister | None, *orgs: LinkedOrganization
) -> tuple[SubscriptionSyncService, Session, Auditor]:
    session, auditor = Session(), Auditor()
    service = SubscriptionSyncService(
        FakeSyncStore(*orgs),
        session,  # type: ignore[arg-type]
        lister,
        auditor,
        PLANS,
    )
    return service, session, auditor


async def test_matching_state_is_in_sync_and_one_audit_row_is_written():
    service, session, auditor = syncer(FakeLister([snapshot()]), org())

    report = await service.reconcile(ADMIN)

    assert (report.stripe_subscriptions, report.in_sync, report.drift_count) == (
        1,
        1,
        0,
    )
    assert not report.truncated and report.drifts == []
    assert session.commits == 1
    assert len(auditor.rows) == 1
    assert auditor.rows[0]["action"] == "admin.subscriptions.sync"
    assert auditor.rows[0]["details"]["in_sync"] == 1


@pytest.mark.parametrize(
    ("stripe", "local", "kind"),
    [
        (snapshot(status="past_due"), org(), "status"),
        (snapshot(price="price_ent_m"), org(), "plan"),
        (snapshot(cancel=True), org(), "cancel_at_period_end"),
        (snapshot(sub_id="sub_2"), org(), "subscription_id"),
        (snapshot(status="canceled"), org(subscription_status="canceled"), "plan"),
        (snapshot(sub_id="sub_9", customer="cus_9"), org(), "unmatched"),
    ],
)
async def test_each_kind_of_drift_is_reported(stripe, local, kind):
    service, _, _ = syncer(FakeLister([stripe]), local)

    report = await service.reconcile(ADMIN)

    assert [d.kind for d in report.drifts][:1] == [kind]
    assert report.in_sync == 0


async def test_an_ended_subscription_stored_as_free_is_in_sync():
    local = org(subscription_tier="free", subscription_status="canceled")
    service, _, _ = syncer(FakeLister([snapshot(status="canceled")]), local)

    assert (await service.reconcile(ADMIN)).in_sync == 1


async def test_an_old_ended_subscription_of_the_same_customer_is_ignored():
    stripe = [snapshot(sub_id="sub_old", status="canceled"), snapshot()]
    service, _, _ = syncer(FakeLister(stripe), org())

    report = await service.reconcile(ADMIN)

    assert (report.historical_ignored, report.in_sync, report.drift_count) == (1, 1, 0)


async def test_a_local_subscription_stripe_does_not_have_is_missing_in_stripe():
    service, _, _ = syncer(FakeLister([]), org())

    report = await service.reconcile(ADMIN)

    assert [(d.kind, d.organization_id) for d in report.drifts] == [
        ("missing_in_stripe", "org1")
    ]


async def test_unmapped_price_does_not_report_plan_drift():
    service, _, _ = syncer(FakeLister([snapshot(price="price_new")]), org())

    assert (await service.reconcile(ADMIN)).in_sync == 1


async def test_pages_are_followed_with_the_cursor():
    items = [snapshot(f"sub_{n}", f"cus_{n}") for n in range(5)]
    orgs = [
        org(
            id=f"o{n}", stripe_customer_id=f"cus_{n}", stripe_subscription_id=f"sub_{n}"
        )
        for n in range(5)
    ]
    lister = FakeLister(items, page_size=2)
    service, _, _ = syncer(lister, *orgs)

    report = await service.reconcile(ADMIN)

    assert lister.cursors == [None, "sub_1", "sub_3"]
    assert (report.stripe_subscriptions, report.in_sync) == (5, 5)


async def test_reading_stops_at_the_page_cap_and_skips_the_missing_check():
    items = [snapshot(f"sub_{n}", f"cus_{n}") for n in range(MAX_PAGES + 2)]
    lister = FakeLister(items, page_size=1)
    service, _, _ = syncer(lister, org(stripe_subscription_id="sub_local"))

    report = await service.reconcile(ADMIN)

    assert report.truncated
    assert len(lister.cursors) == MAX_PAGES
    assert all(d.kind != "missing_in_stripe" for d in report.drifts)


async def test_drift_list_is_capped_but_the_count_is_not():
    items = [snapshot(f"sub_{n}", f"cus_{n}") for n in range(MAX_DRIFTS + 5)]
    service, _, _ = syncer(FakeLister(items))

    report = await service.reconcile(ADMIN)

    assert report.drift_count == MAX_DRIFTS + 5
    assert len(report.drifts) == MAX_DRIFTS


async def test_missing_check_fills_only_the_remaining_drift_slots():
    local = [org(id=f"o{n}", stripe_subscription_id=f"sub_x{n}") for n in range(3)]
    items = [snapshot(f"sub_{n}", f"cus_{n}") for n in range(MAX_DRIFTS - 1)]
    service, _, _ = syncer(FakeLister(items), *local)

    report = await service.reconcile(ADMIN)

    assert len(report.drifts) == MAX_DRIFTS
    assert report.drift_count == MAX_DRIFTS - 1 + 3


async def test_stripe_failure_is_unavailable_and_nothing_is_audited():
    lister = FakeLister([snapshot()])
    lister.fail = True
    service, session, auditor = syncer(lister, org())

    with pytest.raises(SyncUnavailable):
        await service.reconcile(ADMIN)

    assert auditor.rows == [] and session.commits == 0


async def test_without_stripe_the_sync_is_not_configured():
    service, session, auditor = syncer(None)

    with pytest.raises(SyncNotConfigured):
        await service.reconcile(ADMIN)

    assert auditor.rows == [] and session.commits == 0
