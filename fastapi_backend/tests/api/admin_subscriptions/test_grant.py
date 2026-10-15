"""Admin subscriptions e2e (KAN-48): grant a plan and its effect on the merchant side."""

import asyncio

import pytest
from sqlalchemy import text

from app.api.v1.org_billing import stripe_billing
from app.repositories.audit import AuditRepository
from tests.api.admin_subscriptions.support import (
    BASE,
    MANAGER,
    TEST_DATABASE_URL,
    as_user,
    audit_rows,
    grant_url,
    in_days,
    keyed,
    org_columns,
    paying,
    refund_url,
    seed_org,
    seed_owner,
    seed_user,
)
from tests.fakes_billing import FakeStripe

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


# ------------------------------------------------------------------------- grant


async def test_grant_stores_a_plan_apart_from_stripe_state_and_audits_once(
    client, engine, stripe
):
    admin_id = await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)

    result = await client.put(
        grant_url(org_id),
        json={"plan": "pro", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )

    assert result.status_code == 200
    data = result.json()["data"]
    assert (data["organization_id"], data["granted_plan"], data["changed"]) == (
        org_id,
        "pro",
        True,
    )
    tier, status, sub_id, _, granted_plan, granted_until = await org_columns(
        engine, org_id
    )
    assert (tier, status, sub_id) == (
        "free",
        "inactive",
        None,
    )  # Stripe state untouched
    assert granted_plan == "pro" and granted_until is not None
    assert stripe.calls == []  # no Stripe object is created
    entries = await audit_rows(engine, "admin.subscriptions.grant")
    assert len(entries) == 1 and entries[0][0] == admin_id and entries[0][4] == org_id
    assert entries[0][5]["before"]["granted_plan"] is None
    assert entries[0][5]["after"]["granted_plan"] == "pro"
    detail = await client.get(f"{BASE}/{org_id}", headers=as_user("mgr"))
    assert detail.json()["data"]["plan"] == "pro"
    assert detail.json()["data"]["granted_plan"] == "pro"


async def test_granting_the_same_plan_and_expiry_again_changes_nothing(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)
    body = {"plan": "enterprise", "expires_at": in_days(10)}
    await client.put(grant_url(org_id), json=body, headers=as_user("mgr"))

    again = await client.put(grant_url(org_id), json=body, headers=as_user("mgr"))

    assert again.status_code == 200 and again.json()["data"]["changed"] is False
    assert len(await audit_rows(engine, "admin.subscriptions.grant")) == 1


async def test_changing_a_grant_writes_a_second_audit_row_with_before_and_after(
    client, engine
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)
    await client.put(
        grant_url(org_id),
        json={"plan": "pro", "expires_at": in_days(10)},
        headers=as_user("mgr"),
    )

    changed = await client.put(
        grant_url(org_id),
        json={"plan": "enterprise", "expires_at": in_days(20)},
        headers=as_user("mgr"),
    )

    assert changed.json()["data"]["changed"] is True
    entries = await audit_rows(engine, "admin.subscriptions.grant")
    assert len(entries) == 2
    assert entries[1][5]["before"]["granted_plan"] == "pro"
    assert entries[1][5]["after"]["granted_plan"] == "enterprise"


@pytest.mark.parametrize(
    "body",
    [
        {"plan": "free", "expires_at": "2099-01-01T00:00:00Z"},
        {"plan": "gold", "expires_at": "2099-01-01T00:00:00Z"},
        {"plan": "pro"},
        {"plan": "pro", "expires_at": "2099-01-01T00:00:00"},
        {"plan": "pro", "expires_at": "not a date"},
        {"plan": "pro", "expires_at": "2099-01-01T00:00:00Z", "tier": "pro"},
        {"expires_at": "2099-01-01T00:00:00Z"},
    ],
)
async def test_grant_rejects_invalid_bodies_with_422(client, engine, body):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)

    result = await client.put(grant_url(org_id), json=body, headers=as_user("mgr"))

    assert result.status_code == 422
    assert (await org_columns(engine, org_id))[4] is None
    assert await audit_rows(engine) == []


@pytest.mark.parametrize("days", [-1, 0, 731, 4000])
async def test_grant_expiry_must_be_in_the_future_and_within_two_years(
    client, engine, days
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)

    result = await client.put(
        grant_url(org_id),
        json={"plan": "pro", "expires_at": in_days(days)},
        headers=as_user("mgr"),
    )

    assert result.status_code == 422
    assert (await org_columns(engine, org_id))[4] is None
    assert await audit_rows(engine) == []


async def test_grant_beside_a_live_stripe_subscription_is_409(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.put(
        grant_url(org_id),
        json={"plan": "enterprise", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )

    assert result.status_code == 409
    assert (await org_columns(engine, org_id))[4] is None
    assert await audit_rows(engine) == []


async def test_grant_of_an_unknown_organisation_is_404(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)

    result = await client.put(
        grant_url("nope"),
        json={"plan": "pro", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )

    assert result.status_code == 404


async def test_a_later_stripe_webhook_write_neither_removes_nor_contradicts_the_grant(
    client, engine
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)
    await client.put(
        grant_url(org_id),
        json={"plan": "enterprise", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )
    async with engine.begin() as connection:  # what BillingChange applies
        await connection.execute(
            text(
                "UPDATE organizations SET subscription_tier = 'free', "
                "subscription_status = 'canceled', stripe_subscription_id = 'sub_9' "
                "WHERE id = :id"
            ),
            {"id": org_id},
        )

    detail = await client.get(f"{BASE}/{org_id}", headers=as_user("mgr"))

    assert detail.json()["data"]["plan"] == "enterprise"
    assert detail.json()["data"]["status"] == "canceled"


async def test_grant_and_its_audit_row_commit_or_roll_back_together(
    client, engine, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)

    async def broken(self, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditRepository, "add", broken)
    result = await client.put(
        grant_url(org_id),
        json={"plan": "pro", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )

    assert result.status_code == 500
    assert (await org_columns(engine, org_id))[4] is None


async def test_simultaneous_refunds_with_one_key_refund_and_audit_once(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-race-0001")
    body = {"charge_id": "ch_1", "amount": 1000}

    results = await asyncio.gather(
        *(client.post(refund_url(org_id), json=body, headers=headers) for _ in range(4))
    )

    assert [r.status_code for r in results] == [200] * 4
    assert sorted(r.json()["data"]["already_applied"] for r in results) == [
        False,
        True,
        True,
        True,
    ]
    assert stripe.names().count("create_refund") == 1
    assert stripe.charges["ch_1"].amount_refunded == 1000
    assert len(await audit_rows(engine, "admin.subscriptions.refund")) == 1


# ------------------------------------------------- the grant is read by the merchant side


async def test_a_grant_changes_the_plan_the_billing_summary_reports(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    client.app.dependency_overrides[stripe_billing] = lambda: FakeStripe()  # type: ignore[attr-defined]
    org_id = await seed_org(engine)
    await seed_owner(engine, org_id)
    before = await client.get(
        f"/v1/organizations/{org_id}/billing", headers=as_user("owner")
    )

    await client.put(
        grant_url(org_id),
        json={"plan": "enterprise", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )
    after = await client.get(
        f"/v1/organizations/{org_id}/billing", headers=as_user("owner")
    )

    assert before.json()["data"]["plan"]["key"] == "free"
    assert after.json()["data"]["plan"]["key"] == "enterprise"
    assert after.json()["data"]["has_subscription"] is False


async def test_a_grant_raises_the_store_limit_until_it_expires(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)
    await seed_owner(engine, org_id)

    async def new_store(slug: str):
        return await client.post(
            f"/v1/organizations/{org_id}/stores",
            json={"name": slug, "slug": slug},
            headers=as_user("owner"),
        )

    assert (await new_store("first")).status_code == 201
    assert (await new_store("second")).status_code == 409  # free plan: one store
    await client.put(
        grant_url(org_id),
        json={"plan": "pro", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )
    assert (await new_store("second")).status_code == 201
    async with engine.begin() as connection:  # the grant lapses
        await connection.execute(
            text(
                "UPDATE organizations SET granted_until = now() - interval '1 day' "
                "WHERE id = :id"
            ),
            {"id": org_id},
        )
    assert (await new_store("third")).status_code == 409
