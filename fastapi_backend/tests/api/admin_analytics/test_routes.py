"""Admin analytics e2e (KAN-119): permissions, real aggregate queries, sync and its audit row."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.ids import new_id
from tests.api.admin_analytics.support import BASE, ROUTES
from tests.api.admin_subscriptions.support import (
    TEST_DATABASE_URL,
    as_user,
    audit_rows,
    paying,
    seed_org,
    seed_user,
)
from tests.fakes_admin_analytics import snapshot

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

ALL = ["users.read", "subscriptions.read", "settings.read", "subscriptions.sync"]


async def seed_store(engine: AsyncEngine, org_id: str, status: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO stores (id, organization_id, name, slug, status) "
                "VALUES (:id, :org, 'S', :slug, :status)"
            ),
            {
                "id": new_id(),
                "org": org_id,
                "slug": f"s-{new_id().lower()}",
                "status": status,
            },
        )


@pytest.mark.parametrize(("method", "path", "permission"), ROUTES)
async def test_unauthenticated_request_is_401(client, engine, method, path, permission):
    result = await client.request(method, path)

    assert result.status_code == 401
    assert await audit_rows(engine) == []


@pytest.mark.parametrize(("method", "path", "permission"), ROUTES)
async def test_signed_in_user_without_an_admin_record_is_403(
    client, engine, method, path, permission
):
    await seed_user(engine, "plain")

    result = await client.request(method, path, headers=as_user("plain"))

    assert result.status_code == 403
    assert await audit_rows(engine) == []


@pytest.mark.parametrize(("method", "path", "permission"), ROUTES)
async def test_admin_holding_only_another_permission_is_403(
    client, engine, method, path, permission
):
    other = next(p for _, _, p in ROUTES if p != permission)
    await seed_user(engine, "limited", "admin", [other])

    result = await client.request(method, path, headers=as_user("limited"))

    assert result.status_code == 403
    assert await audit_rows(engine) == []


async def test_overview_counts_users_organisations_and_stores(client, engine):
    await seed_user(engine, "boss", "super_admin", ["*"])
    await seed_user(engine, "ann")
    first = await seed_org(engine)
    second = await seed_org(engine)
    await seed_store(engine, first, "ACTIVE")
    await seed_store(engine, first, "ACTIVE")
    await seed_store(engine, second, "FAILED")

    result = await client.get(f"{BASE}/overview", headers=as_user("boss"))

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    data = result.json()["data"]
    assert data["users"] == {
        "total": 2,
        "verified": 2,
        "new_this_month": 2,
        "active_last_30_days": 0,
        "admins": 1,
    }
    assert data["organizations"] == {"total": 2, "new_this_month": 2}
    assert data["stores_by_status"] == {"ACTIVE": 2, "FAILED": 1}
    assert "email" not in result.text


async def test_revenue_comes_from_organisation_billing_with_one_read_per_price(
    client, engine, prices
):
    await seed_user(engine, "boss", "super_admin", ["*"])
    for index in range(3):
        await seed_org(
            engine,
            **paying(
                stripe_customer_id=f"cus_{index}", stripe_subscription_id=f"sub_{index}"
            ),
        )
    await seed_org(
        engine,
        **paying(
            stripe_customer_id="cus_y",
            stripe_subscription_id="sub_y",
            stripe_price_id="price_pro_y",
            subscription_status="past_due",
        ),
    )
    await seed_org(
        engine,
        **paying(
            stripe_customer_id="cus_t",
            stripe_subscription_id="sub_t",
            subscription_status="trialing",
            stripe_cancel_at_period_end=True,
        ),
    )
    await seed_org(engine)  # free, no subscription

    result = await client.get(f"{BASE}/revenue", headers=as_user("boss"))

    assert result.status_code == 200
    data = result.json()["data"]
    assert data["mrr_minor"] == 3 * 2900 + 2000
    assert data["arr_minor"] == data["mrr_minor"] * 12
    assert data["billed_organizations"] == 4 and data["complete"] is True
    assert data["currency"] == "USD"
    assert data["by_plan"] == [{"plan": "pro", "organizations": 4, "mrr_minor": 10700}]
    assert data["organizations_by_status"] == {
        "active": 3,
        "past_due": 1,
        "trialing": 1,
        "inactive": 1,
    }
    assert data["cancelling_at_period_end"] == 1
    assert sorted(prices.calls) == ["price_pro_m", "price_pro_y"]


async def test_revenue_uses_the_platform_currency_setting(client, engine):
    await seed_user(engine, "boss", "super_admin", ["*"])
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO app_settings (id, key, value, category) "
                "VALUES (:id, 'currency', CAST('\"gbp\"' AS jsonb), 'general')"
            ),
            {"id": new_id()},
        )

    result = await client.get(f"{BASE}/revenue", headers=as_user("boss"))

    assert result.json()["data"]["currency"] == "GBP"


async def test_system_stats_count_platform_tables(client, engine):
    await seed_user(engine, "boss", "super_admin", ["*"])
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO feature_flags (id, name, enabled, rollout_percentage) "
                "VALUES (:id, 'beta', true, 100)"
            ),
            {"id": new_id()},
        )

    result = await client.get(f"{BASE}/system", headers=as_user("boss"))

    assert result.status_code == 200
    data = result.json()["data"]
    assert data["feature_flags"] == 1 and data["admin_users"] == 1
    assert set(data) >= {"app_settings", "audit_logs", "stripe_events", "redirects"}


async def test_sync_reports_drift_and_writes_one_audit_row_without_changing_data(
    client, engine, lister
):
    await seed_user(engine, "boss", "super_admin", ["*"])
    synced = await seed_org(engine, **paying())
    drifted = await seed_org(
        engine,
        **paying(stripe_customer_id="cus_2", stripe_subscription_id="sub_2"),
    )
    gone = await seed_org(
        engine,
        **paying(stripe_customer_id="cus_3", stripe_subscription_id="sub_3"),
    )
    lister.items = [
        snapshot(),
        snapshot("sub_2", "cus_2", status="past_due"),
        snapshot("sub_9", "cus_9"),
    ]

    result = await client.post(f"{BASE}/subscription-sync", headers=as_user("boss"))

    assert result.status_code == 200
    data = result.json()["data"]
    assert (data["stripe_subscriptions"], data["in_sync"], data["drift_count"]) == (
        3,
        1,
        3,
    )
    found = {(d["kind"], d["organization_id"]) for d in data["drifts"]}
    assert found == {
        ("status", drifted),
        ("unmatched", None),
        ("missing_in_stripe", gone),
    }
    assert synced not in {d["organization_id"] for d in data["drifts"]}
    audit = await audit_rows(engine, "admin.subscriptions.sync")
    assert len(audit) == 1
    assert audit[0].metadata["details"]["drift_count"] == 3
    async with engine.connect() as connection:
        statuses = (
            await connection.execute(
                text("SELECT subscription_status FROM organizations WHERE id = :id"),
                {"id": drifted},
            )
        ).scalar_one()
    assert statuses == "active"


async def test_sync_is_502_when_stripe_fails_and_audits_the_failure(
    client, engine, lister
):
    await seed_user(engine, "boss", "super_admin", ["*"])
    lister.fail = True

    result = await client.post(f"{BASE}/subscription-sync", headers=as_user("boss"))

    assert result.status_code == 502
    assert result.json() == {
        "success": False,
        "error": "Billing provider unavailable",
    }
    audit = await audit_rows(engine, "admin.subscriptions.sync")
    assert len(audit) == 1
    assert audit[0].metadata["details"] == {"outcome": "unavailable"}


async def test_sync_is_503_when_stripe_is_not_configured(client, engine):
    from app.api.v1.admin_analytics import stripe_lister

    client.app.dependency_overrides[stripe_lister] = lambda: None  # type: ignore[attr-defined]
    await seed_user(engine, "boss", "super_admin", ["*"])

    result = await client.post(f"{BASE}/subscription-sync", headers=as_user("boss"))

    assert result.status_code == 503
    assert await audit_rows(engine) == []


async def test_revenue_is_incomplete_when_a_price_cannot_be_read(
    client, engine, prices
):
    await seed_user(engine, "boss", "super_admin", ["*"])
    await seed_org(engine, **paying())
    prices.amounts.clear()

    result = await client.get(f"{BASE}/revenue", headers=as_user("boss"))

    data = result.json()["data"]
    assert data["complete"] is False and data["unpriced_organizations"] == 1
    assert data["mrr_minor"] == 0
