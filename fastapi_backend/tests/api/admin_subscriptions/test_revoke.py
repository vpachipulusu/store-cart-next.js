"""Admin subscriptions e2e (KAN-199): revoke a granted plan. See the support module."""

import pytest
from sqlalchemy import text

from app.repositories.admin_subscriptions import AdminSubscriptionsRepository
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
    seed_org,
    seed_user,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

ACTION = "admin.subscriptions.revoke_grant"


async def _granted_org(client, engine, plan: str = "pro", **columns) -> str:
    org_id = await seed_org(engine, **columns)
    result = await client.put(
        grant_url(org_id),
        json={"plan": plan, "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )
    assert result.status_code == 200
    return org_id


async def test_revoke_clears_the_grant_and_audits_intent_then_result(client, engine):
    admin_id = await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)

    result = await client.delete(grant_url(org_id), headers=keyed("mgr"))

    assert result.status_code == 200
    assert result.json()["data"] == {
        "organization_id": org_id,
        "already_applied": False,
    }
    columns = await org_columns(engine, org_id)
    assert columns[4] is None and columns[5] is None
    entries = await audit_rows(engine, ACTION)
    assert len(entries) == 1 and entries[0][0] == admin_id and entries[0][4] == org_id
    assert entries[0][5]["before"]["granted_plan"] == "pro"
    assert entries[0][5]["details"]["state"] == "completed"
    assert "key-aaaa-0001" not in str(entries[0][5])


async def test_organisation_falls_back_to_its_free_plan_after_revoke(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine, "enterprise")

    await client.delete(grant_url(org_id), headers=keyed("mgr"))

    detail = await client.get(f"{BASE}/{org_id}", headers=as_user("mgr"))
    assert detail.json()["data"]["plan"] == "free"
    assert detail.json()["data"]["granted_plan"] is None


async def test_revoke_falls_back_to_the_stripe_derived_plan_without_touching_stripe(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(
        engine,
        subscription_tier="pro",
        subscription_status="canceled",
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
    )
    await client.put(
        grant_url(org_id),
        json={"plan": "enterprise", "expires_at": in_days(30)},
        headers=as_user("mgr"),
    )
    before = await org_columns(engine, org_id)

    await client.delete(grant_url(org_id), headers=keyed("mgr"))

    after = await org_columns(engine, org_id)
    assert after[:4] == before[:4]
    assert stripe.calls == []
    detail = await client.get(f"{BASE}/{org_id}", headers=as_user("mgr"))
    assert detail.json()["data"]["plan"] == "pro"


async def test_revoke_retry_with_the_same_key_is_a_no_op(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)
    headers = keyed("mgr", "key-retry-0001")
    await client.delete(grant_url(org_id), headers=headers)
    await client.put(  # a newer grant must survive the replayed delete
        grant_url(org_id),
        json={"plan": "enterprise", "expires_at": in_days(5)},
        headers=as_user("mgr"),
    )

    replay = await client.delete(grant_url(org_id), headers=headers)

    assert replay.status_code == 200 and replay.json()["data"]["already_applied"]
    assert (await org_columns(engine, org_id))[4] == "enterprise"
    assert len(await audit_rows(engine, ACTION)) == 1


async def test_revoke_without_a_grant_is_409_and_not_audited(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.delete(grant_url(org_id), headers=keyed("mgr"))

    assert result.status_code == 409
    assert await audit_rows(engine, ACTION) == []


async def test_revoke_of_an_unknown_organisation_is_404(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)

    result = await client.delete(grant_url("nope"), headers=keyed("mgr"))

    assert result.status_code == 404


async def test_revoke_requires_an_idempotency_key(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)

    result = await client.delete(grant_url(org_id), headers=as_user("mgr"))

    assert result.status_code == 422
    assert (await org_columns(engine, org_id))[4] == "pro"


async def test_revoke_needs_the_grant_permission(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    await seed_user(engine, "reader", "admin", ["subscriptions.read"])
    org_id = await _granted_org(client, engine)

    result = await client.delete(grant_url(org_id), headers=keyed("reader"))

    assert result.status_code == 403
    assert (await org_columns(engine, org_id))[4] == "pro"
    assert await audit_rows(engine, ACTION) == []


async def test_revoke_audit_failure_leaves_the_grant_and_the_retry_succeeds(
    client, engine, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)
    headers = keyed("mgr", "key-retry-0002")
    original = AuditRepository.add

    async def broken(self, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditRepository, "add", broken)
    failed = await client.delete(grant_url(org_id), headers=headers)
    assert (await org_columns(engine, org_id))[4] == "pro"
    monkeypatch.setattr(AuditRepository, "add", original)
    retry = await client.delete(grant_url(org_id), headers=headers)

    assert failed.status_code == 503
    assert "retry with the same Idempotency-Key" in failed.json()["error"]
    assert retry.status_code == 200 and retry.json()["data"]["already_applied"] is False
    assert (await org_columns(engine, org_id))[4] is None
    assert len(await audit_rows(engine, ACTION)) == 1


async def test_revoke_failure_after_the_intent_row_keeps_it_pending_and_retry_finishes(
    client, engine, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)
    headers = keyed("mgr", "key-retry-0003")
    original = AdminSubscriptionsRepository.clear_grant

    async def broken(self, organization_id):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(AdminSubscriptionsRepository, "clear_grant", broken)
    failed = await client.delete(grant_url(org_id), headers=headers)
    pending = await audit_rows(engine, ACTION)
    monkeypatch.setattr(AdminSubscriptionsRepository, "clear_grant", original)
    retry = await client.delete(grant_url(org_id), headers=headers)

    assert failed.status_code == 503
    # the trail exists before the change is applied
    assert len(pending) == 1 and pending[0][5]["details"]["state"] == "pending"
    assert retry.status_code == 200 and retry.json()["data"]["already_applied"] is False
    assert (await org_columns(engine, org_id))[4] is None
    entries = await audit_rows(engine, ACTION)
    assert len(entries) == 1 and entries[0][5]["details"]["state"] == "completed"


async def test_an_expired_grant_can_still_be_cleared(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE organizations SET granted_until = now() - interval '1 day' "
                "WHERE id = :id"
            ),
            {"id": org_id},
        )

    result = await client.delete(grant_url(org_id), headers=keyed("mgr"))

    assert result.status_code == 200
    assert (await org_columns(engine, org_id))[4] is None


async def test_resumed_revoke_never_clears_a_newer_grant(client, engine, monkeypatch):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)
    headers = keyed("mgr", "key-retry-0004")
    original = AdminSubscriptionsRepository.clear_grant

    async def broken(self, organization_id):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(AdminSubscriptionsRepository, "clear_grant", broken)
    failed = await client.delete(grant_url(org_id), headers=headers)
    monkeypatch.setattr(AdminSubscriptionsRepository, "clear_grant", original)
    await client.put(
        grant_url(org_id),
        json={"plan": "enterprise", "expires_at": in_days(5)},
        headers=as_user("mgr"),
    )

    retry = await client.delete(grant_url(org_id), headers=headers)

    assert failed.status_code == 503
    assert retry.status_code == 200 and retry.json()["data"]["already_applied"] is True
    assert (await org_columns(engine, org_id))[4] == "enterprise"
    entries = await audit_rows(engine, ACTION)
    assert len(entries) == 1 and entries[0][5]["details"]["state"] == "superseded"
    assert entries[0][5]["before"]["granted_plan"] == "pro"


async def test_completed_revoke_row_records_the_cleared_state(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)

    await client.delete(grant_url(org_id), headers=keyed("mgr"))

    details = (await audit_rows(engine, ACTION))[0][5]["details"]
    assert details["after"] == {"granted_plan": None, "granted_until": None}
    assert details["granted_plan"] == "pro" and details["completed_at"]


async def test_second_revoke_with_a_new_key_after_the_first_is_409(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await _granted_org(client, engine)
    await client.delete(grant_url(org_id), headers=keyed("mgr", "key-first-0001"))

    second = await client.delete(
        grant_url(org_id), headers=keyed("mgr", "key-second-0002")
    )

    assert second.status_code == 409
    assert len(await audit_rows(engine, ACTION)) == 1
