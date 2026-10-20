"""The refund call on a connected account (KAN-80), against a mock transport."""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.stripe_billing import StripeError, StripeNotConfigured, StripeRejected
from app.core.stripe_refunds import (
    HttpStripeRefunds,
    RefundRequest,
    StripeRefund,
    get_stripe_refunds,
)

SECRET = "sk_test_unit_only_not_real"
REQUEST = RefundRequest(
    account_id="acct_merchant1",
    payment_intent_id="pi_123",
    amount_minor=2400,
    store_id="store1",
    order_id="order1",
    refund_id="refund1",
)


def client_for(handler: Any, seen: list[httpx.Request]) -> HttpStripeRefunds:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return HttpStripeRefunds(
        SECRET, httpx.AsyncClient(transport=httpx.MockTransport(record))
    )


async def test_the_refund_is_made_on_the_connected_account_with_our_ids():
    seen: list[httpx.Request] = []
    stripe = client_for(
        lambda r: httpx.Response(200, json={"id": "re_1", "status": "pending"}), seen
    )

    refund = await stripe.create_refund(REQUEST)

    request = seen[0]
    assert refund == StripeRefund("re_1", "pending")
    assert request.url.path == "/v1/refunds"
    assert request.headers["Stripe-Account"] == "acct_merchant1"
    assert request.headers["Idempotency-Key"] == "refund-refund1"
    assert {k: v[0] for k, v in parse_qs(request.content.decode()).items()} == {
        "payment_intent": "pi_123",
        "amount": "2400",
        "metadata[store_id]": "store1",
        "metadata[order_id]": "order1",
        "metadata[refund_id]": "refund1",
    }
    assert "refund_application_fee" not in request.content.decode()


async def test_a_refusal_is_a_rejection():
    stripe = client_for(lambda r: httpx.Response(400, json={"error": {}}), [])

    with pytest.raises(StripeRejected):
        await stripe.create_refund(REQUEST)


@pytest.mark.parametrize("body", [{"id": "re_1"}, {"status": "pending"}, {"id": 1}])
async def test_an_unusable_answer_is_an_error(body: dict[str, Any]):
    stripe = client_for(lambda r: httpx.Response(200, json=body), [])

    with pytest.raises(StripeError):
        await stripe.create_refund(REQUEST)


def test_the_client_needs_a_stripe_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    with pytest.raises(StripeNotConfigured):
        get_stripe_refunds()

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))
    assert isinstance(get_stripe_refunds(), HttpStripeRefunds)
