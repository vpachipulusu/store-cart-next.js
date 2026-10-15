"""Admin subscriptions e2e (KAN-48): cancel a subscription. See the support module."""

import json
from dataclasses import replace

import pytest
from sqlalchemy import text

from app.api.v1.admin_subscriptions import stripe_admin
from app.repositories.audit import AuditRepository
from tests.api.admin_subscriptions.support import (
    BASE,
    MANAGER,
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


# ------------------------------------------------------------------------ cancel


async def test_cancel_at_period_end_asks_stripe_and_writes_one_audit_row(
    client, engine, stripe
):
    admin_id = await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr", "key-aaaa-0001")
    )

    assert result.status_code == 200
    assert result.json()["data"] == {
        "organization_id": org_id,
        "immediately": False,
        "already_applied": False,
    }
    call = stripe.last("set_cancel_at_period_end")
    assert call["subscription_id"] == "sub_1" and call["cancel"] is True
    assert call["idempotency_key"] == f"sc-admin-cancel:{org_id}:key-aaaa-0001"
    entries = await audit_rows(engine, "admin.subscriptions.cancel")
    assert len(entries) == 1
    user_id, _, resource, resource_id, organization_id, metadata = entries[0]
    assert (user_id, resource, resource_id, organization_id) == (
        admin_id,
        "subscriptions",
        org_id,
        org_id,
    )
    assert metadata["details"]["immediately"] is False
    assert "key-aaaa-0001" not in json.dumps(metadata)
    # The webhook is the only writer of subscription state.
    assert (await org_columns(engine, org_id))[:4] == ("pro", "active", "sub_1", False)


async def test_cancel_immediately_deletes_the_subscription(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        f"{BASE}/{org_id}/cancel", json={"immediately": True}, headers=keyed("mgr")
    )

    assert result.status_code == 200 and result.json()["data"]["immediately"] is True
    assert "cancel_subscription" in stripe.names()
    assert "set_cancel_at_period_end" not in stripe.names()
    assert (await org_columns(engine, org_id))[:2] == ("pro", "active")
    assert len(await audit_rows(engine, "admin.subscriptions.cancel")) == 1


async def test_cancel_without_a_body_defaults_to_period_end(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(f"{BASE}/{org_id}/cancel", headers=keyed("mgr"))

    assert result.status_code == 200
    assert "set_cancel_at_period_end" in stripe.names()


async def test_cancel_retry_with_the_same_key_is_a_no_op(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-retry-0001")
    first = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=headers)
    stripe.calls.clear()

    again = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=headers)

    assert first.json()["data"]["already_applied"] is False
    assert again.status_code == 200 and again.json()["data"]["already_applied"] is True
    assert stripe.calls == []
    assert len(await audit_rows(engine, "admin.subscriptions.cancel")) == 1


async def test_cancel_retry_after_the_webhook_marked_it_cancelling_still_succeeds(
    client, engine
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-retry-0002")
    await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=headers)
    async with engine.begin() as connection:  # the webhook applies the change
        await connection.execute(
            text(
                "UPDATE organizations SET stripe_cancel_at_period_end = true "
                "WHERE id = :id"
            ),
            {"id": org_id},
        )

    again = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=headers)

    assert again.status_code == 200 and again.json()["data"]["already_applied"] is True
    assert len(await audit_rows(engine, "admin.subscriptions.cancel")) == 1


async def test_cancel_when_stripe_already_shows_it_ending_is_audited_without_a_second_call(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying(stripe_cancel_at_period_end=True))
    stripe.subscription = replace(stripe.subscription, cancel_at_period_end=True)

    result = await client.post(
        f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr", "key-other-0001")
    )

    assert result.status_code == 200
    assert "set_cancel_at_period_end" not in stripe.names()
    assert len(await audit_rows(engine, "admin.subscriptions.cancel")) == 1


async def test_cancel_at_period_end_of_a_subscription_stripe_shows_ended_is_409(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    stripe.subscription = replace(stripe.subscription, status="canceled")

    result = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 409
    assert "set_cancel_at_period_end" not in stripe.names()
    assert await audit_rows(engine) == []


async def test_immediate_cancel_retry_after_a_lost_audit_row_and_the_webhook_is_audited_once(
    client, engine, stripe, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-lost-0002")
    original = AuditRepository.add

    async def broken(self, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditRepository, "add", broken)
    failed = await client.post(
        f"{BASE}/{org_id}/cancel", json={"immediately": True}, headers=headers
    )
    monkeypatch.setattr(AuditRepository, "add", original)
    async with engine.begin() as connection:  # the webhook applies the cancellation
        await connection.execute(
            text(
                "UPDATE organizations SET subscription_status = 'canceled', "
                "subscription_tier = 'free' WHERE id = :id"
            ),
            {"id": org_id},
        )

    retry = await client.post(
        f"{BASE}/{org_id}/cancel", json={"immediately": True}, headers=headers
    )

    assert failed.status_code == 503
    assert retry.status_code == 200
    assert stripe.names().count("cancel_subscription") == 1
    assert len(await audit_rows(engine, "admin.subscriptions.cancel")) == 1


async def test_cancel_reusing_a_key_for_another_mode_is_409(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-mode-0001")
    await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=headers)

    clash = await client.post(
        f"{BASE}/{org_id}/cancel", json={"immediately": True}, headers=headers
    )

    assert clash.status_code == 409
    assert len(await audit_rows(engine, "admin.subscriptions.cancel")) == 1


@pytest.mark.parametrize("key", ["short", "has space 1234", "x" * 65, "bad/key/123456"])
async def test_cancel_requires_a_well_formed_idempotency_key(
    client, engine, stripe, key
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr", key)
    )

    assert result.status_code == 422 and stripe.calls == []


async def test_cancel_without_an_idempotency_key_is_422(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        f"{BASE}/{org_id}/cancel", json={}, headers=as_user("mgr")
    )

    assert result.status_code == 422 and stripe.calls == []


async def test_cancel_rejects_unknown_body_fields(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        f"{BASE}/{org_id}/cancel",
        json={"immediately": True, "subscription_id": "sub_other"},
        headers=keyed("mgr"),
    )

    assert result.status_code == 422 and stripe.calls == []


@pytest.mark.parametrize(
    "columns",
    [
        {},
        {"stripe_customer_id": "cus_1"},
    ],
)
async def test_cancel_without_a_live_subscription_is_409(
    client, engine, stripe, columns
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **columns)

    result = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 409
    assert stripe.calls == [] and await audit_rows(engine) == []


async def test_cancel_refuses_a_subscription_of_another_customer(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    stripe.subscription = stripe.subscription.__class__(
        "sub_1", "cus_other", None, None
    )

    result = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 409
    assert "set_cancel_at_period_end" not in stripe.names()
    assert await audit_rows(engine) == []


async def test_cancel_of_an_unknown_organisation_is_404(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)

    result = await client.post(f"{BASE}/nope/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 404


async def test_cancel_stripe_outage_is_a_generic_502_with_no_audit_row(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    stripe.fail = True

    result = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 502
    assert result.json() == {"success": False, "error": "Billing provider unavailable"}
    assert await audit_rows(engine) == []


async def test_cancel_stripe_refusal_is_a_generic_409(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    stripe.reject = True

    result = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 409
    assert "stripe" not in result.text.lower()
    assert await audit_rows(engine) == []


async def test_cancel_without_a_stripe_key_is_503(client, engine):
    client.app.dependency_overrides[stripe_admin] = lambda: None  # type: ignore[attr-defined]
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 503 and await audit_rows(engine) == []


async def test_cancel_when_stripe_no_longer_knows_the_subscription_is_a_409(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    stripe.missing_subscription = True

    result = await client.post(f"{BASE}/{org_id}/cancel", json={}, headers=keyed("mgr"))

    assert result.status_code == 409
    assert await audit_rows(engine) == []
