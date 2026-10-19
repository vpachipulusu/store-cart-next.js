from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core import stripe_admin
from app.core.config import settings
from app.core.stripe_admin import HttpStripeAdmin, get_stripe_admin
from app.core.stripe_billing import (
    StripeConflict,
    StripeError,
    StripeNotFound,
    StripeRejected,
)

SECRET = "sk_test_unit_only_not_real"
CHARGE = {
    "id": "ch_1",
    "customer": "cus_1",
    "amount": 5000,
    "amount_captured": 5000,
    "amount_refunded": 1200,
    "currency": "gbp",
    "status": "succeeded",
    "captured": True,
    "created": 1_800_000_000,
    "invoice": "in_1",
    "payment_method_details": {"card": {"last4": "4242", "brand": "visa"}},
    "billing_details": {"email": "buyer@example.com"},
}


def client_for(
    handler: Any, seen: list[httpx.Request] | None = None
) -> HttpStripeAdmin:
    def record(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)
    return HttpStripeAdmin(SECRET, httpx.AsyncClient(transport=transport))


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


async def test_get_charge_keeps_only_money_fields_and_no_card_data():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: httpx.Response(200, json=CHARGE), seen)

    charge = await stripe.get_charge("ch_1")

    assert seen[0].url.path == "/v1/charges/ch_1"
    assert (charge.id, charge.customer_id, charge.currency) == ("ch_1", "cus_1", "gbp")
    assert (charge.amount_captured, charge.amount_refunded) == (5000, 1200)
    assert charge.refundable == 3800
    assert charge.invoice_id == "in_1"
    assert "4242" not in repr(charge) and "buyer@example.com" not in repr(charge)


async def test_charge_with_expanded_customer_and_invoice_is_read_by_id():
    body = {**CHARGE, "customer": {"id": "cus_9"}, "invoice": {"id": "in_9"}}
    stripe = client_for(lambda r: httpx.Response(200, json=body))

    charge = await stripe.get_charge("ch_1")

    assert (charge.customer_id, charge.invoice_id) == ("cus_9", "in_9")


async def test_uncaptured_or_failed_charge_is_not_refundable():
    body = {**CHARGE, "captured": False, "amount_captured": 0, "status": "pending"}
    stripe = client_for(lambda r: httpx.Response(200, json=body))

    assert (await stripe.get_charge("ch_1")).refundable == 0


async def test_fully_refunded_charge_has_nothing_left_to_refund():
    body = {**CHARGE, "amount_refunded": 5000}
    stripe = client_for(lambda r: httpx.Response(200, json=body))

    assert (await stripe.get_charge("ch_1")).refundable == 0


async def test_list_charges_asks_for_the_customers_latest_charges():
    seen: list[httpx.Request] = []
    stripe = client_for(
        lambda r: httpx.Response(200, json={"data": [CHARGE, "junk"]}), seen
    )

    charges = await stripe.list_charges("cus_1")

    assert dict(seen[0].url.params) == {"customer": "cus_1", "limit": "12"}
    assert [c.id for c in charges] == ["ch_1"]


async def test_create_refund_sends_charge_amount_reason_and_idempotency_key():
    seen: list[httpx.Request] = []
    stripe = client_for(
        lambda r: httpx.Response(
            200,
            json={
                "id": "re_1",
                "amount": 300,
                "currency": "gbp",
                "status": "succeeded",
            },
        ),
        seen,
    )

    refund = await stripe.create_refund(
        charge_id="ch_1",
        amount=300,
        reason="requested_by_customer",
        organization_id="org1",
        request_ref="ref123",
        idempotency_key="sc-admin-refund-org1-k",
    )

    assert (refund.id, refund.amount, refund.currency) == ("re_1", 300, "gbp")
    assert seen[0].url.path == "/v1/refunds"
    assert seen[0].headers["Idempotency-Key"] == "sc-admin-refund-org1-k"
    assert form(seen[0]) == {
        "charge": "ch_1",
        "amount": "300",
        "reason": "requested_by_customer",
        "metadata[organization_id]": "org1",
        "metadata[request_ref]": "ref123",
    }


async def test_refund_without_a_reason_omits_it():
    seen: list[httpx.Request] = []
    stripe = client_for(
        lambda r: httpx.Response(
            200, json={"id": "re_1", "amount": 1, "currency": "gbp"}
        ),
        seen,
    )

    await stripe.create_refund(
        charge_id="ch_1",
        amount=1,
        reason=None,
        organization_id="o",
        request_ref="r",
        idempotency_key="k",
    )

    assert "reason" not in form(seen[0])


async def test_refund_response_without_an_amount_is_a_stripe_error():
    stripe = client_for(lambda r: httpx.Response(200, json={"id": "re_1"}))

    with pytest.raises(StripeError):
        await stripe.create_refund(
            charge_id="ch_1",
            amount=1,
            reason=None,
            organization_id="o",
            request_ref="r",
            idempotency_key="k",
        )


async def test_cancel_subscription_deletes_it_with_an_idempotency_key():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: httpx.Response(200, json={"id": "sub_1"}), seen)

    await stripe.cancel_subscription("sub_1", idempotency_key="sc-admin-cancel-x")

    assert (seen[0].method, seen[0].url.path) == ("DELETE", "/v1/subscriptions/sub_1")
    assert seen[0].headers["Idempotency-Key"] == "sc-admin-cancel-x"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (404, StripeNotFound),
        (400, StripeRejected),
        (402, StripeRejected),
        (409, StripeConflict),  # a StripeRejected subclass (KAN-68)
        (429, StripeError),
        (500, StripeError),
    ],
)
async def test_http_failures_map_to_distinct_errors_without_stripe_text(status, error):
    stripe = client_for(
        lambda r: httpx.Response(status, json={"error": {"message": "secret detail"}})
    )

    with pytest.raises(error) as caught:
        await stripe.get_charge("ch_1")

    assert type(caught.value) is error
    assert "secret detail" not in str(caught.value)


def test_factory_requires_the_secret_key(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)

    with pytest.raises(stripe_admin.StripeNotConfigured):
        get_stripe_admin()


def test_factory_builds_the_real_client(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))

    assert isinstance(get_stripe_admin(), HttpStripeAdmin)


async def test_find_refund_returns_the_refund_carrying_the_request_reference():
    seen: list[httpx.Request] = []
    body = {
        "data": [
            {"id": "re_0", "amount": 5, "currency": "gbp", "metadata": {}},
            "junk",
            {
                "id": "re_1",
                "amount": 300,
                "currency": "gbp",
                "status": "succeeded",
                "metadata": {"request_ref": "ref123"},
            },
        ]
    }
    stripe = client_for(lambda r: httpx.Response(200, json=body), seen)

    refund = await stripe.find_refund("ch_1", "ref123")

    assert refund is not None and (refund.id, refund.amount) == ("re_1", 300)
    assert dict(seen[0].url.params) == {"charge": "ch_1", "limit": "100"}


async def test_find_refund_returns_none_when_no_refund_matches():
    stripe = client_for(
        lambda r: httpx.Response(200, json={"data": [{"id": "re_0", "amount": 5}]})
    )

    assert await stripe.find_refund("ch_1", "ref123") is None
