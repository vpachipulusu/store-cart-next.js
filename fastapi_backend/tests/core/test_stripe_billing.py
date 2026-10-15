from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core import stripe_billing
from app.core.config import settings
from app.core.stripe_billing import (
    HttpStripeBilling,
    StripeError,
    StripeNotConfigured,
    StripeNotFound,
    get_stripe_billing,
)

SECRET = "sk_test_unit_only_not_real"


def client_for(
    handler: Any, seen: list[httpx.Request] | None = None
) -> HttpStripeBilling:
    def record(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)
    return HttpStripeBilling(SECRET, httpx.AsyncClient(transport=transport))


def json_response(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


async def test_create_customer_sends_idempotency_key_and_metadata_only():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: json_response({"id": "cus_1"}), seen)

    customer = await stripe.create_customer(
        name="Acme", organization_id="org1", idempotency_key="k-1"
    )

    request = seen[0]
    assert customer == "cus_1"
    assert request.url.path == "/v1/customers"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert request.headers["Idempotency-Key"] == "k-1"
    assert form(request) == {"name": "Acme", "metadata[organization_id]": "org1"}


async def test_checkout_session_is_a_subscription_for_one_price():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: json_response({"url": "https://c.test/x"}), seen)

    url = await stripe.create_checkout_session(
        customer_id="cus_1",
        price_id="price_1",
        organization_id="org1",
        success_url="https://app.test/ok",
        cancel_url="https://app.test/no",
        idempotency_key="k-2",
    )

    sent = form(seen[0])
    assert url == "https://c.test/x"
    assert seen[0].url.path == "/v1/checkout/sessions"
    assert sent["mode"] == "subscription"
    assert sent["line_items[0][price]"] == "price_1"
    assert sent["customer"] == "cus_1"
    assert sent["subscription_data[metadata][organization_id]"] == "org1"
    assert seen[0].headers["Idempotency-Key"] == "k-2"


async def test_portal_session_returns_its_url():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: json_response({"url": "https://p.test/x"}), seen)

    url = await stripe.create_portal_session(
        customer_id="cus_1", return_url="https://app.test/b", idempotency_key="k-3"
    )

    assert url == "https://p.test/x"
    assert form(seen[0]) == {"customer": "cus_1", "return_url": "https://app.test/b"}


async def test_get_subscription_reads_customer_item_and_price():
    body = {
        "id": "sub_1",
        "customer": "cus_1",
        "items": {"data": [{"id": "si_1", "price": {"id": "price_1"}}]},
    }
    stripe = client_for(lambda r: json_response(body))

    subscription = await stripe.get_subscription("sub_1")

    assert (subscription.customer_id, subscription.item_id, subscription.price_id) == (
        "cus_1",
        "si_1",
        "price_1",
    )


async def test_get_subscription_without_items_has_no_item():
    body = {"id": "sub_1", "customer": "cus_1", "items": {"data": []}}
    stripe = client_for(lambda r: json_response(body))

    subscription = await stripe.get_subscription("sub_1")

    assert subscription.item_id is None


async def test_change_price_prorates_and_cancel_flag_is_sent_as_text():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: json_response({"id": "sub_1"}), seen)

    await stripe.change_subscription_price(
        subscription_id="sub_1", item_id="si_1", price_id="price_2", idempotency_key="k"
    )
    await stripe.set_cancel_at_period_end(
        subscription_id="sub_1", cancel=True, idempotency_key="k2"
    )
    await stripe.set_cancel_at_period_end(
        subscription_id="sub_1", cancel=False, idempotency_key="k3"
    )

    assert form(seen[0])["proration_behavior"] == "create_prorations"
    assert form(seen[0])["items[0][price]"] == "price_2"
    assert form(seen[1]) == {"cancel_at_period_end": "true"}
    assert form(seen[2]) == {"cancel_at_period_end": "false"}


async def test_list_invoices_keeps_only_the_safe_fields():
    body = {
        "data": [
            {
                "id": "in_1",
                "number": "A-1",
                "status": "paid",
                "amount_due": 500,
                "amount_paid": 500,
                "currency": "gbp",
                "created": 1_800_000_000,
                "hosted_invoice_url": "https://i.test/1",
                "invoice_pdf": "https://i.test/1.pdf",
                "customer_email": "private@example.com",
            },
            "junk",
        ]
    }
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: json_response(body), seen)

    invoices = await stripe.list_invoices("cus_1")

    assert len(invoices) == 1
    assert invoices[0].amount_paid == 500
    assert not hasattr(invoices[0], "customer_email")
    assert seen[0].url.params["customer"] == "cus_1"


async def test_list_payment_methods_keeps_card_summary_only():
    body = {
        "data": [
            {
                "id": "pm_1",
                "card": {
                    "brand": "visa",
                    "last4": "4242",
                    "exp_month": 1,
                    "exp_year": 2031,
                },
            },
            {"id": "pm_2"},
            "junk",
        ]
    }
    stripe = client_for(lambda r: json_response(body))

    methods = await stripe.list_payment_methods("cus_1")

    assert len(methods) == 2
    assert (methods[0].brand, methods[0].last4, methods[0].exp_year) == (
        "visa",
        "4242",
        2031,
    )
    assert methods[1].last4 is None


@pytest.mark.parametrize("status", [400, 402, 404, 429, 500])
async def test_http_error_becomes_a_generic_stripe_error(status):
    stripe = client_for(
        lambda r: json_response({"error": {"message": "secret detail"}}, status)
    )

    with pytest.raises(StripeError) as caught:
        await stripe.get_subscription("sub_1")

    assert "secret detail" not in str(caught.value)


async def test_transport_failure_becomes_a_generic_stripe_error():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out talking to api.stripe.com")

    with pytest.raises(StripeError) as caught:
        await client_for(boom).get_subscription("sub_1")

    assert "stripe.com" not in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=["list"]),
        httpx.Response(200, json={"id": ""}),
    ],
)
async def test_unusable_response_is_a_stripe_error(response):
    stripe = client_for(lambda r: response)

    with pytest.raises(StripeError):
        await stripe.create_customer(
            name="A", organization_id="o", idempotency_key="k-1"
        )


async def test_failures_are_logged_without_bodies_or_secrets(caplog):
    stripe = client_for(
        lambda r: json_response({"error": {"message": "card 4242 declined"}}, 402)
    )

    with caplog.at_level("DEBUG"), pytest.raises(StripeError):
        await stripe.list_invoices("cus_1")

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert logged
    assert "4242" not in logged
    assert SECRET not in logged
    assert "cus_1" not in logged


async def test_client_without_injected_transport_opens_its_own(monkeypatch):
    class Mocked(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(
                transport=httpx.MockTransport(lambda r: json_response({"id": "cus_9"}))
            )

    monkeypatch.setattr(stripe_billing.httpx, "AsyncClient", Mocked)

    customer = await HttpStripeBilling(SECRET).create_customer(
        name="A", organization_id="o", idempotency_key="k-1"
    )

    assert customer == "cus_9"


def test_factory_requires_the_secret_key(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)

    with pytest.raises(StripeNotConfigured):
        get_stripe_billing()


def test_factory_builds_the_real_client_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))

    assert isinstance(get_stripe_billing(), HttpStripeBilling)


def test_factory_treats_an_empty_key_as_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(""))

    with pytest.raises(StripeNotConfigured):
        get_stripe_billing()


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        ("pm_1", "pm_1"),
        ({"id": "pm_2", "object": "payment_method"}, "pm_2"),
        (None, None),
    ],
)
async def test_default_payment_method_is_read_from_the_customer(setting, expected):
    seen: list[httpx.Request] = []
    body = {"id": "cus_1", "invoice_settings": {"default_payment_method": setting}}
    stripe = client_for(lambda r: json_response(body), seen)

    assert await stripe.get_default_payment_method_id("cus_1") == expected
    assert (seen[0].method, seen[0].url.path) == ("GET", "/v1/customers/cus_1")


@pytest.mark.parametrize(
    ("customer", "expected"),
    [("cus_1", "cus_1"), ({"id": "cus_2"}, "cus_2"), (None, None)],
)
async def test_payment_method_owner_is_read_from_the_payment_method(customer, expected):
    stripe = client_for(lambda r: json_response({"id": "pm_1", "customer": customer}))

    assert await stripe.get_payment_method_customer_id("pm_1") == expected


async def test_a_missing_payment_method_is_stripe_not_found():
    stripe = client_for(lambda r: json_response({"error": {}}, 404))

    with pytest.raises(StripeNotFound):
        await stripe.get_payment_method_customer_id("pm_missing")


async def test_detach_and_set_default_send_the_expected_requests():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: json_response({"id": "x"}), seen)

    await stripe.detach_payment_method(payment_method_id="pm_1", idempotency_key="k-1")
    await stripe.set_default_payment_method(
        customer_id="cus_1", payment_method_id="pm_2", idempotency_key="k-2"
    )

    assert seen[0].url.path == "/v1/payment_methods/pm_1/detach"
    assert seen[0].headers["Idempotency-Key"] == "k-1"
    assert seen[1].url.path == "/v1/customers/cus_1"
    assert form(seen[1]) == {"invoice_settings[default_payment_method]": "pm_2"}
