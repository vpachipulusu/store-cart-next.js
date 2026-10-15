"""Admin subscriptions e2e (KAN-48): authentication, list and detail. See the support module."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.api.v1.admin_subscriptions import stripe_admin
from app.core.ids import new_id
from tests.api.admin_subscriptions.support import (
    BASE,
    GRANT_BODY,
    MANAGER,
    ROUTES,
    TEST_DATABASE_URL,
    as_user,
    audit_rows,
    keyed,
    org_columns,
    paying,
    seed_org,
    seed_user,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


# ---------------------------------------------------------------- authentication


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_unauthenticated_request_is_401(client, engine, method, path, body):
    result = await client.request(
        method, path, json=body, headers={"Idempotency-Key": "key-aaaa-0001"}
    )

    assert result.status_code == 401
    assert await audit_rows(engine) == []


async def test_wrong_internal_key_is_rejected(client):
    result = await client.get(BASE, headers={"X-Internal-Key": "wrong"})

    assert result.status_code in (401, 403)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_merchant_who_owns_the_organisation_is_403_and_nothing_changes(
    client, engine, stripe, method, path, body
):
    owner = await seed_user(engine, "owner")
    org_id = await seed_org(engine, **paying())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO memberships (id, organization_id, user_id, role) "
                "VALUES (:id, :org, :user, 'OWNER')"
            ),
            {"id": new_id(), "org": org_id, "user": owner},
        )

    result = await client.request(
        method,
        path.replace("org1", org_id),
        json=body,
        headers=keyed("owner", "key-aaaa-0001"),
    )

    assert result.status_code == 403
    assert result.json() == {"success": False, "error": "Forbidden"}
    assert stripe.calls == [] and await audit_rows(engine) == []


@pytest.mark.parametrize(
    ("method", "path", "body", "needs"),
    [
        ("GET", BASE, None, "subscriptions.read"),
        ("GET", f"{BASE}/org1", None, "subscriptions.read"),
        ("POST", f"{BASE}/org1/cancel", {}, "subscriptions.update"),
        ("POST", f"{BASE}/org1/refunds", {"charge_id": "ch_1"}, "subscriptions.refund"),
        ("PUT", f"{BASE}/org1/grant", GRANT_BODY, "subscriptions.grant"),
    ],
)
async def test_admin_missing_the_exact_permission_is_403_and_changes_nothing(
    client, engine, stripe, method, path, body, needs
):
    await seed_user(engine, "partial", "admin", [p for p in MANAGER if p != needs])
    org_id = await seed_org(engine, **paying())

    result = await client.request(
        method,
        path.replace("org1", org_id),
        json=body,
        headers=keyed("partial", "key-aaaa-0001"),
    )

    assert result.status_code == 403
    assert result.json() == {"success": False, "error": "Forbidden"}
    assert stripe.calls == [] and await audit_rows(engine) == []
    assert (await org_columns(engine, org_id))[4] is None


async def test_user_without_an_admin_record_is_403(client, engine):
    await seed_user(engine, "plain")

    result = await client.get(BASE, headers=as_user("plain"))

    assert result.status_code == 403


# -------------------------------------------------------------------------- list


async def test_list_shows_subscribed_organisations_newest_first_without_secrets(
    client, engine
):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    older = await seed_org(
        engine, **paying(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    newer = await seed_org(
        engine,
        **paying(
            stripe_customer_id="cus_2",
            stripe_subscription_id="sub_2",
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        ),
    )
    await seed_org(engine)  # free, no subscription: not listed

    result = await client.get(BASE, headers=as_user("reader"))

    body = result.json()["data"]
    assert [s["organization_id"] for s in body["subscriptions"]] == [newer, older]
    assert body["total_count"] == 2
    assert (body["limit"], body["offset"]) == (20, 0)
    assert result.headers["cache-control"] == "no-store"
    assert "cus_" not in result.text and "sub_" not in result.text
    assert "price_" not in result.text


async def test_list_filters_by_status_and_by_effective_plan(client, engine):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    pro_active = await seed_org(engine, **paying())
    canceled = await seed_org(
        engine,
        **paying(
            stripe_customer_id="cus_2",
            stripe_subscription_id="sub_2",
            subscription_tier="free",
            subscription_status="canceled",
        ),
    )
    granted = await seed_org(
        engine,
        granted_plan="enterprise",
        granted_until=datetime.now(UTC) + timedelta(days=5),
    )
    await seed_org(  # an expired grant on a free organisation is not a subscription
        engine,
        granted_plan="pro",
        granted_until=datetime.now(UTC) - timedelta(days=1),
    )

    by_status = await client.get(f"{BASE}?status=canceled", headers=as_user("reader"))
    enterprise = await client.get(f"{BASE}?plan=enterprise", headers=as_user("reader"))
    pro = await client.get(f"{BASE}?plan=pro", headers=as_user("reader"))
    free = await client.get(f"{BASE}?plan=free", headers=as_user("reader"))

    def ids(response):
        return {s["organization_id"] for s in response.json()["data"]["subscriptions"]}

    assert ids(by_status) == {canceled}
    assert ids(enterprise) == {granted}
    assert ids(pro) == {pro_active}
    assert ids(free) == {canceled}


async def test_sql_plan_filter_and_python_effective_plan_agree(client, engine):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    soon = datetime.now(UTC) + timedelta(days=3)
    past = datetime.now(UTC) - timedelta(days=3)
    cases = [
        {
            "subscription_tier": "pro",
            "granted_plan": "enterprise",
            "granted_until": soon,
        },
        {
            "subscription_tier": "enterprise",
            "granted_plan": "pro",
            "granted_until": soon,
        },
        {
            "subscription_tier": "pro",
            "granted_plan": "enterprise",
            "granted_until": past,
        },
        {"subscription_tier": "free", "granted_plan": "pro", "granted_until": soon},
        {"subscription_tier": "legacy", "granted_plan": "pro", "granted_until": soon},
        {"subscription_tier": "enterprise"},
        {"subscription_tier": "free"},
    ]
    for index, extra in enumerate(cases):
        await seed_org(
            engine,
            stripe_subscription_id=f"sub_{index}",
            stripe_customer_id=f"cus_{index}",
            **extra,
        )

    total = 0
    for plan in ("free", "pro", "enterprise"):
        page = (
            await client.get(f"{BASE}?plan={plan}&limit=100", headers=as_user("reader"))
        ).json()["data"]
        assert {s["plan"] for s in page["subscriptions"]} <= {plan}
        assert page["total_count"] == len(page["subscriptions"])
        total += page["total_count"]
    assert total == len(cases)


async def test_list_pages_are_stable_and_bounded(client, engine):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    same_second = datetime(2026, 3, 1, tzinfo=UTC)
    for index in range(5):
        await seed_org(
            engine,
            **paying(
                stripe_customer_id=f"cus_{index}",
                stripe_subscription_id=f"sub_{index}",
                created_at=same_second,
            ),
        )

    pages = [
        await client.get(f"{BASE}?limit=2&offset={offset}", headers=as_user("reader"))
        for offset in (0, 2, 4)
    ]

    seen = [
        s["organization_id"]
        for page in pages
        for s in page.json()["data"]["subscriptions"]
    ]
    assert len(seen) == 5 and len(set(seen)) == 5
    assert pages[0].json()["data"]["total_count"] == 5


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1", "status=bogus", "plan=gold", "limit=abc"],
)
async def test_list_rejects_invalid_filters_and_paging_with_422(client, engine, query):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])

    result = await client.get(f"{BASE}?{query}", headers=as_user("reader"))

    assert result.status_code == 422
    assert result.json() == {"success": False, "error": "Invalid request"}


# ------------------------------------------------------------------------ detail


async def test_detail_returns_the_organisation_and_recent_payments_only(
    client, engine, stripe
):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    org_id = await seed_org(engine, **paying())

    result = await client.get(f"{BASE}/{org_id}", headers=as_user("reader"))

    data = result.json()["data"]
    assert data["organization_id"] == org_id
    assert data["plan"] == "pro" and data["status"] == "active"
    assert [p["charge_id"] for p in data["payments"]] == [
        "ch_1",
        "ch_pending",
        "ch_refunded",
    ]  # the customer's own charges only, never ch_other
    assert data["payments"][0]["refundable"] == 5000
    assert [p["refundable"] for p in data["payments"][1:]] == [0, 0]
    assert data["payments"][0]["currency"] == "gbp"
    assert stripe.names() == ["list_charges"]
    for forbidden in ("last4", "secret", "password", "token", "email", "brand"):
        assert forbidden not in result.text.lower()


async def test_detail_without_a_stripe_customer_has_no_payments_and_no_stripe_call(
    client, engine, stripe
):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    org_id = await seed_org(engine)

    result = await client.get(f"{BASE}/{org_id}", headers=as_user("reader"))

    assert result.json()["data"]["payments"] == []
    assert result.json()["data"]["plan"] == "free"
    assert stripe.calls == []


async def test_detail_still_answers_when_stripe_fails(client, engine, stripe):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    org_id = await seed_org(engine, **paying())
    stripe.fail = True

    result = await client.get(f"{BASE}/{org_id}", headers=as_user("reader"))

    assert result.status_code == 200
    assert result.json()["data"]["payments"] is None


async def test_detail_without_a_stripe_key_still_answers(client, engine):
    client.app.dependency_overrides[stripe_admin] = lambda: None  # type: ignore[attr-defined]
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    org_id = await seed_org(engine, **paying())

    result = await client.get(f"{BASE}/{org_id}", headers=as_user("reader"))

    assert result.status_code == 200 and result.json()["data"]["payments"] is None


async def test_detail_of_an_unknown_organisation_is_404(client, engine):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])

    result = await client.get(f"{BASE}/nope", headers=as_user("reader"))

    assert result.status_code == 404
    assert result.json() == {"success": False, "error": "Organization not found"}


async def test_detail_rejects_a_malformed_organisation_id(client, engine):
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])

    result = await client.get(f"{BASE}/bad%20id", headers=as_user("reader"))

    assert result.status_code == 422
