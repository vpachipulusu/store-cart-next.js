from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.stripe_billing import StripeError, StripeNotConfigured
from app.core.stripe_connect import HttpStripeConnect, get_stripe_connect

SECRET = "sk_test_unit_only_not_real"


def client_for(handler: Any, seen: list[httpx.Request]) -> HttpStripeConnect:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)
    return HttpStripeConnect(SECRET, httpx.AsyncClient(transport=transport))


def form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


async def test_create_account_requests_an_express_account_with_the_two_capabilities():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: httpx.Response(200, json={"id": "acct_1"}), seen)

    account = await stripe.create_account(organization_id="org1", idempotency_key="k-1")

    request = seen[0]
    assert account == "acct_1"
    assert request.url.path == "/v1/accounts"
    assert request.headers["Idempotency-Key"] == "k-1"
    assert form(request) == {
        "type": "express",
        "capabilities[card_payments][requested]": "true",
        "capabilities[transfers][requested]": "true",
        "metadata[organization_id]": "org1",
    }


async def test_create_account_link_is_an_onboarding_link_with_both_urls():
    seen: list[httpx.Request] = []
    stripe = client_for(
        lambda r: httpx.Response(200, json={"url": "https://connect.stripe.test/x"}),
        seen,
    )

    url = await stripe.create_account_link(
        account_id="acct_1",
        refresh_url="https://app.example.com/a",
        return_url="https://app.example.com/b",
        idempotency_key="k-2",
    )

    assert url == "https://connect.stripe.test/x"
    assert seen[0].url.path == "/v1/account_links"
    assert form(seen[0]) == {
        "account": "acct_1",
        "type": "account_onboarding",
        "refresh_url": "https://app.example.com/a",
        "return_url": "https://app.example.com/b",
    }


async def test_unusable_response_and_stripe_errors_raise_without_stripe_text():
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: httpx.Response(200, json={}), seen)
    with pytest.raises(StripeError):
        await stripe.create_account(organization_id="org1", idempotency_key="k-1")

    failing = client_for(
        lambda r: httpx.Response(500, json={"error": {"message": "secret detail"}}),
        seen,
    )
    with pytest.raises(StripeError) as raised:
        await failing.create_account_link(
            account_id="acct_1", refresh_url="r", return_url="u", idempotency_key="k"
        )
    assert "secret detail" not in str(raised.value)


def test_factory_requires_the_secret_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    with pytest.raises(StripeNotConfigured):
        get_stripe_connect()

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))
    assert isinstance(get_stripe_connect(), HttpStripeConnect)


async def test_get_account_reads_the_three_capability_flags():
    seen: list[httpx.Request] = []
    body = {
        "charges_enabled": True,
        "payouts_enabled": False,
        "details_submitted": True,
    }
    stripe = client_for(lambda r: httpx.Response(200, json=body), seen)

    state = await stripe.get_account("acct_1")

    assert seen[0].method == "GET" and seen[0].url.path == "/v1/accounts/acct_1"
    assert (state.charges_enabled, state.payouts_enabled, state.details_submitted) == (
        True,
        False,
        True,
    )


async def test_a_403_reading_an_account_is_a_distinct_forbidden_error():
    from app.core.stripe_billing import StripeForbidden

    stripe = client_for(lambda r: httpx.Response(403, json={"error": {}}), [])

    with pytest.raises(StripeForbidden):
        await stripe.get_account("acct_1")


async def test_get_account_treats_missing_or_non_boolean_flags_as_off():
    stripe = client_for(
        lambda r: httpx.Response(200, json={"charges_enabled": "true"}), []
    )

    state = await stripe.get_account("acct_1")

    assert (state.charges_enabled, state.payouts_enabled, state.details_submitted) == (
        False,
        False,
        False,
    )
