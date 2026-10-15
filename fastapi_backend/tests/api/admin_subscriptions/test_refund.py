"""Admin subscriptions e2e (KAN-48): refund a payment. See the support module."""

import json

import pytest

from app.api.v1.admin_subscriptions import stripe_admin
from app.repositories.audit import AuditRepository
from tests.api.admin_subscriptions.support import (
    MANAGER,
    TEST_DATABASE_URL,
    as_user,
    audit_rows,
    keyed,
    paying,
    refund_url,
    seed_org,
    seed_user,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


# ------------------------------------------------------------------------ refund


async def test_refund_without_an_amount_refunds_what_is_left_and_audits_once(
    client, engine, stripe
):
    admin_id = await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 5000},
        headers=keyed("mgr"),
    )

    assert result.status_code == 200
    assert result.json()["data"] == {
        "organization_id": org_id,
        "refund_id": "re_1",
        "charge_id": "ch_1",
        "amount": 5000,
        "currency": "gbp",
        "status": "succeeded",
        "already_applied": False,
    }
    call = stripe.last("create_refund")
    assert call["amount"] == 5000 and call["organization_id"] == org_id
    assert call["idempotency_key"] == f"sc-admin-refund:{org_id}:key-aaaa-0001"
    entries = await audit_rows(engine, "admin.subscriptions.refund")
    assert len(entries) == 1
    assert entries[0][0] == admin_id and entries[0][4] == org_id
    details = entries[0][5]["details"]
    assert details["charge_id"] == "ch_1" and details["amount"] == 5000
    assert details["currency"] == "gbp" and details["refund_id"] == "re_1"
    assert "key-aaaa-0001" not in json.dumps(entries[0][5])


async def test_partial_refund_keeps_the_rest_refundable(client, engine):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    first = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 1200, "reason": "duplicate"},
        headers=keyed("mgr", "key-part-0001"),
    )
    rest = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 3800},
        headers=keyed("mgr", "key-part-0002"),
    )
    nothing_left = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 1},
        headers=keyed("mgr", "key-part-0003"),
    )

    assert first.json()["data"]["amount"] == 1200
    assert rest.json()["data"]["amount"] == 3800
    assert nothing_left.status_code == 409
    assert len(await audit_rows(engine, "admin.subscriptions.refund")) == 2


async def test_refund_retry_with_the_same_key_does_not_refund_twice(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-twice-0001")
    first = await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 700}, headers=headers
    )
    stripe.calls.clear()

    again = await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 700}, headers=headers
    )

    assert again.status_code == 200
    assert again.json()["data"]["refund_id"] == first.json()["data"]["refund_id"]
    assert again.json()["data"]["already_applied"] is True
    assert stripe.calls == []
    assert stripe.charges["ch_1"].amount_refunded == 700
    assert len(await audit_rows(engine, "admin.subscriptions.refund")) == 1


async def test_refund_retry_after_a_lost_audit_write_replays_stripe_and_audits_once(
    client, engine, stripe, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-lost-0001")
    original = AuditRepository.add

    async def broken(self, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditRepository, "add", broken)
    failed = await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 5000}, headers=headers
    )
    monkeypatch.setattr(AuditRepository, "add", original)

    retry = await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 5000}, headers=headers
    )

    assert failed.status_code == 500
    assert retry.status_code == 200 and retry.json()["data"]["amount"] == 5000
    assert stripe.charges["ch_1"].amount_refunded == 5000  # Stripe replayed: one refund
    assert len(await audit_rows(engine, "admin.subscriptions.refund")) == 1


async def test_refund_reusing_a_key_for_another_amount_is_409(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-clash-0001")
    await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 700}, headers=headers
    )

    clash = await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 800}, headers=headers
    )

    assert clash.status_code == 409
    assert stripe.charges["ch_1"].amount_refunded == 700
    assert len(await audit_rows(engine, "admin.subscriptions.refund")) == 1


async def test_refund_more_than_refundable_is_409_and_moves_no_money(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 5001},
        headers=keyed("mgr"),
    )

    assert result.status_code == 409
    assert result.json()["error"] == "Amount exceeds the refundable balance"
    assert stripe.charges["ch_1"].amount_refunded == 0
    assert await audit_rows(engine) == []


@pytest.mark.parametrize(
    "body",
    [
        {"charge_id": "ch_1"},
        {"charge_id": "ch_1", "amount": None},
        {"charge_id": "ch_1", "amount": 0},
        {"charge_id": "ch_1", "amount": -5},
        {"charge_id": "ch_1", "amount": 10.5},
        {"charge_id": "ch_1", "amount": "100"},
        {"charge_id": "ch_1", "amount": True},
        {"charge_id": "ch_1", "amount": 100_000_000},
        {"charge_id": "ch_1", "currency": "usd"},
        {"charge_id": "ch_1", "reason": "because"},
        {"charge_id": "pi_123"},
        {"charge_id": "ch_1/../x"},
        {"charge_id": ""},
        {},
    ],
)
async def test_refund_rejects_invalid_input_with_422(client, engine, stripe, body):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(refund_url(org_id), json=body, headers=keyed("mgr"))

    assert result.status_code == 422
    assert stripe.calls == [] and await audit_rows(engine) == []


async def test_refund_of_another_customers_charge_is_rejected_like_an_unknown_one(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    other = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_other", "amount": 100},
        headers=keyed("mgr"),
    )
    unknown = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_nope", "amount": 100},
        headers=keyed("mgr", "key-aaaa-0002"),
    )

    assert other.status_code == unknown.status_code == 404
    assert (
        other.json()
        == unknown.json()
        == {"success": False, "error": "Payment not found"}
    )
    assert "create_refund" not in stripe.names()
    assert stripe.charges["ch_other"].amount_refunded == 0
    assert await audit_rows(engine) == []


async def test_refund_for_an_organisation_without_a_customer_is_404(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine)

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 5000},
        headers=keyed("mgr"),
    )

    assert result.status_code == 404 and stripe.calls == []


@pytest.mark.parametrize("charge_id", ["ch_pending", "ch_refunded"])
async def test_refund_of_an_uncaptured_or_fully_refunded_charge_is_409(
    client, engine, stripe, charge_id
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": charge_id, "amount": 100},
        headers=keyed("mgr"),
    )

    assert result.status_code == 409
    assert stripe.charges[charge_id].amount_refunded in (0, 5000)  # unchanged
    assert await audit_rows(engine) == []


async def test_refund_of_an_unknown_organisation_is_404(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)

    result = await client.post(
        refund_url("nope"),
        json={"charge_id": "ch_1", "amount": 5000},
        headers=keyed("mgr"),
    )

    assert result.status_code == 404 and stripe.calls == []


async def test_refund_requires_an_idempotency_key(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 5000},
        headers=as_user("mgr"),
    )

    assert result.status_code == 422 and stripe.calls == []


async def test_refund_stripe_outage_is_a_generic_502_with_no_audit_row(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    stripe.fail = True

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 5000},
        headers=keyed("mgr"),
    )

    assert result.status_code == 502
    assert result.json() == {"success": False, "error": "Billing provider unavailable"}
    assert await audit_rows(engine) == []


async def test_refund_stripe_refusal_is_a_generic_409(client, engine, stripe):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    stripe.reject = True

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 5000},
        headers=keyed("mgr"),
    )

    assert result.status_code == 409
    assert result.json()["error"] == "The billing provider refused the request"
    assert await audit_rows(engine) == []


async def test_refund_without_a_stripe_key_is_503(client, engine):
    client.app.dependency_overrides[stripe_admin] = lambda: None  # type: ignore[attr-defined]
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 5000},
        headers=keyed("mgr"),
    )

    assert result.status_code == 503 and await audit_rows(engine) == []
