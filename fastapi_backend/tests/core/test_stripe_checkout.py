"""The Checkout Session call on a connected account (KAN-68), against a mock transport."""

from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.stripe_billing import StripeConflict, StripeError, StripeNotConfigured
from app.core.stripe_checkout import (
    CheckoutLineItem,
    CheckoutSessionRequest,
    HttpStripeCheckout,
    get_stripe_checkout,
)

SECRET = "sk_test_unit_only_not_real"
REQUEST = CheckoutSessionRequest(
    account_id="acct_merchant1",
    currency="gbp",
    line_items=(
        CheckoutLineItem("Mug (Large)", 1000, 2),
        CheckoutLineItem("Shipping", 499, 1),
    ),
    application_fee_minor=None,
    store_id="store1",
    order_id="order1",
    success_url="https://north.example.com/ok",
    cancel_url="https://north.example.com/cart",
    idempotency_key="sc-checkout-store1-order1",
)
CREATED = {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}


def client_for(handler: Any, seen: list[httpx.Request]) -> HttpStripeCheckout:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return HttpStripeCheckout(
        SECRET, httpx.AsyncClient(transport=httpx.MockTransport(record))
    )


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


async def test_session_is_created_on_the_connected_account_without_a_fee():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: httpx.Response(200, json=CREATED), seen)

    session = await stripe.create_payment_session(REQUEST)

    request = seen[0]
    assert (session.id, session.url) == (CREATED["id"], CREATED["url"])
    assert request.url.path == "/v1/checkout/sessions"
    assert request.headers["Stripe-Account"] == "acct_merchant1"
    assert request.headers["Idempotency-Key"] == "sc-checkout-store1-order1"
    assert form(request) == {
        "mode": "payment",
        "success_url": "https://north.example.com/ok",
        "cancel_url": "https://north.example.com/cart",
        "client_reference_id": "order1",
        "metadata[store_id]": "store1",
        "metadata[order_id]": "order1",
        "payment_intent_data[metadata][store_id]": "store1",
        "payment_intent_data[metadata][order_id]": "order1",
        "line_items[0][quantity]": "2",
        "line_items[0][price_data][currency]": "gbp",
        "line_items[0][price_data][unit_amount]": "1000",
        "line_items[0][price_data][product_data][name]": "Mug (Large)",
        "line_items[1][quantity]": "1",
        "line_items[1][price_data][currency]": "gbp",
        "line_items[1][price_data][unit_amount]": "499",
        "line_items[1][price_data][product_data][name]": "Shipping",
    }


async def test_a_platform_fee_is_sent_as_the_application_fee():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: httpx.Response(200, json=CREATED), seen)

    await stripe.create_payment_session(replace(REQUEST, application_fee_minor=37))

    assert form(seen[0])["payment_intent_data[application_fee_amount]"] == "37"


@pytest.mark.parametrize(
    "body",
    [{}, {"id": "cs_1"}, {"id": "cs_1", "url": "http://checkout.stripe.com/x"}],
)
async def test_an_unusable_response_raises(body: dict[str, str]):
    stripe = client_for(lambda r: httpx.Response(200, json=body), [])

    with pytest.raises(StripeError):
        await stripe.create_payment_session(REQUEST)


async def test_a_stripe_error_carries_no_stripe_text():
    stripe = client_for(
        lambda r: httpx.Response(400, json={"error": {"message": "secret detail"}}),
        [],
    )

    with pytest.raises(StripeError) as raised:
        await stripe.create_payment_session(REQUEST)

    assert "secret detail" not in str(raised.value)


def test_factory_requires_the_secret_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    with pytest.raises(StripeNotConfigured):
        get_stripe_checkout()

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))
    assert isinstance(get_stripe_checkout(), HttpStripeCheckout)


async def test_a_409_is_a_conflict_not_a_refusal():
    stripe = client_for(lambda r: httpx.Response(409, json={}), [])

    with pytest.raises(StripeConflict):
        await stripe.create_payment_session(REQUEST)
