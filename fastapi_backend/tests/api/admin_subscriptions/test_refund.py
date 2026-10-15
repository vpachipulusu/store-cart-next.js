"""Admin subscriptions e2e (KAN-48): refund a payment. See the support module."""

import asyncio
import json

import pytest
from sqlalchemy import text

from app.api.v1.admin_subscriptions import stripe_admin
from app.repositories.admin_subscriptions import AdminSubscriptionsRepository
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


async def test_refund_commit_failure_after_stripe_acted_is_a_503_and_the_retry_completes(
    client, engine, stripe, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-lost-0001")
    original = AdminSubscriptionsRepository.update_request

    async def broken(self, row_id, metadata):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AdminSubscriptionsRepository, "update_request", broken)
    failed = await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 5000}, headers=headers
    )
    monkeypatch.setattr(AdminSubscriptionsRepository, "update_request", original)

    pending = await audit_rows(engine, "admin.subscriptions.refund")
    retry = await client.post(
        refund_url(org_id), json={"charge_id": "ch_1", "amount": 5000}, headers=headers
    )

    assert failed.status_code == 503
    assert "retry with the same Idempotency-Key" in failed.json()["error"]
    assert pending[0][5]["details"]["state"] == "pending"  # intent survived
    assert retry.status_code == 200 and retry.json()["data"]["amount"] == 5000
    assert stripe.charges["ch_1"].amount_refunded == 5000  # one refund only
    final = await audit_rows(engine, "admin.subscriptions.refund")
    assert len(final) == 1 and final[0][5]["details"]["state"] == "completed"


async def test_refund_retry_after_stripe_forgot_the_key_finds_the_refund_not_a_second_one(
    client, engine, stripe, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-late-0001")
    body = {"charge_id": "ch_1", "amount": 2000}

    async def broken(self, row_id, metadata):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AdminSubscriptionsRepository, "update_request", broken)
    failed = await client.post(refund_url(org_id), json=body, headers=headers)
    monkeypatch.undo()
    stripe.forget_idempotency_keys()  # the 24 hour window has passed

    retry = await client.post(refund_url(org_id), json=body, headers=headers)

    assert failed.status_code == 503 and retry.status_code == 200
    assert stripe.names().count("create_refund") == 1
    assert stripe.charges["ch_1"].amount_refunded == 2000
    assert len(await audit_rows(engine, "admin.subscriptions.refund")) == 1


async def test_refund_intent_is_written_before_stripe_is_asked_to_move_money(
    client, engine, stripe, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    seen: list[int] = []
    original = stripe.create_refund

    async def spy(**kwargs):
        seen.append(len(await audit_rows(engine, "admin.subscriptions.refund")))
        return await original(**kwargs)

    monkeypatch.setattr(stripe, "create_refund", spy)

    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 500},
        headers=keyed("mgr"),
    )

    assert result.status_code == 200 and seen == [1]


async def test_refund_intent_that_cannot_be_written_is_a_503_and_stripe_is_not_asked(
    client, engine, stripe, monkeypatch
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())

    async def broken(self, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditRepository, "add", broken)
    result = await client.post(
        refund_url(org_id),
        json={"charge_id": "ch_1", "amount": 500},
        headers=keyed("mgr"),
    )

    assert result.status_code == 503
    assert "create_refund" not in stripe.names()
    assert stripe.charges["ch_1"].amount_refunded == 0


async def test_refund_stripe_failure_after_the_intent_leaves_a_failed_row_and_can_be_retried(
    client, engine, stripe
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-fail-0001")
    body = {"charge_id": "ch_1", "amount": 500}
    stripe.fail_refund = True

    failed = await client.post(refund_url(org_id), json=body, headers=headers)
    rows_after = await audit_rows(engine, "admin.subscriptions.refund")
    stripe.fail_refund = False
    retry = await client.post(refund_url(org_id), json=body, headers=headers)

    assert failed.status_code == 502
    assert len(rows_after) == 1 and rows_after[0][5]["details"]["state"] == "failed"
    assert retry.status_code == 200 and retry.json()["data"]["already_applied"] is False
    final = await audit_rows(engine, "admin.subscriptions.refund")
    assert len(final) == 1 and final[0][5]["details"]["state"] == "completed"
    assert stripe.charges["ch_1"].amount_refunded == 500


async def test_a_damaged_completed_audit_row_is_a_409_not_a_server_error(
    client, engine
):
    await seed_user(engine, "mgr", "admin", MANAGER)
    org_id = await seed_org(engine, **paying())
    headers = keyed("mgr", "key-bad-00001")
    body = {"charge_id": "ch_1", "amount": 500}
    await client.post(refund_url(org_id), json=body, headers=headers)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE audit_logs SET metadata = jsonb_set(metadata, "
                "'{details,refund_id}', '123'::jsonb) WHERE action = :a"
            ),
            {"a": "admin.subscriptions.refund"},
        )

    again = await client.post(refund_url(org_id), json=body, headers=headers)

    assert again.status_code == 409


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
