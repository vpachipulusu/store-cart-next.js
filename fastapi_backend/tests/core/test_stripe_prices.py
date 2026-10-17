"""HttpStripePrices (KAN-208): reads one price's unit amount and nothing else."""

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core import stripe_prices
from app.core.config import settings
from app.core.stripe_billing import StripeError, StripeNotFound
from app.core.stripe_prices import HttpStripePrices, get_stripe_prices

SECRET = "sk_test_unit_only_not_real"


def client_for(
    handler: Any, seen: list[httpx.Request] | None = None
) -> HttpStripePrices:
    def record(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)
    return HttpStripePrices(SECRET, httpx.AsyncClient(transport=transport))


async def test_returns_the_unit_amount_in_minor_units() -> None:
    seen: list[httpx.Request] = []
    prices = client_for(
        lambda r: httpx.Response(200, json={"id": "price_1", "unit_amount": 1900}),
        seen,
    )

    amount = await prices.get_unit_amount("price_1")

    assert amount == 1900
    assert seen[0].method == "GET" and seen[0].url.path == "/v1/prices/price_1"


@pytest.mark.parametrize("unit_amount", [None, "1900", 19.5, -1, True])
async def test_missing_or_malformed_amount_is_none(unit_amount: Any) -> None:
    prices = client_for(
        lambda r: httpx.Response(200, json={"unit_amount": unit_amount})
    )

    assert await prices.get_unit_amount("price_1") is None


@pytest.mark.parametrize("price_id", ["", "prod_1", "price_1/../customers", "price 1"])
async def test_ids_that_are_not_price_ids_never_reach_stripe(price_id: str) -> None:
    seen: list[httpx.Request] = []
    prices = client_for(lambda r: httpx.Response(200, json={"unit_amount": 1}), seen)

    assert await prices.get_unit_amount(price_id) is None
    assert seen == []


async def test_unknown_price_raises_not_found() -> None:
    prices = client_for(lambda r: httpx.Response(404, json={"error": "private"}))

    with pytest.raises(StripeNotFound):
        await prices.get_unit_amount("price_1")


async def test_outage_raises_a_sanitized_error() -> None:
    prices = client_for(lambda r: httpx.Response(500, text="sk_live_secret"))

    with pytest.raises(StripeError) as caught:
        await prices.get_unit_amount("price_1")

    assert "sk_live" not in str(caught.value)


def test_factory_returns_none_without_a_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)

    assert get_stripe_prices() is None


def test_factory_builds_the_http_client_with_the_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr(SECRET))

    assert isinstance(get_stripe_prices(), HttpStripePrices)
    assert stripe_prices.PRICE_ID.fullmatch("price_1Abc")


async def test_get_price_returns_amount_and_upper_case_currency() -> None:
    stripe = client_for(
        lambda r: httpx.Response(200, json={"unit_amount": 2900, "currency": "gbp"})
    )

    price = await stripe.get_price("price_abc")

    assert price is not None
    assert (price.unit_amount, price.currency) == (2900, "GBP")


@pytest.mark.parametrize(
    "body",
    [
        {"unit_amount": None, "currency": "gbp"},
        {"unit_amount": -1, "currency": "gbp"},
        {"unit_amount": 100},
        {"unit_amount": 100, "currency": 5},
    ],
)
async def test_get_price_without_a_usable_amount_or_currency_is_none(
    body: Any,
) -> None:
    stripe = client_for(lambda r: httpx.Response(200, json=body))

    assert await stripe.get_price("price_abc") is None


async def test_get_price_never_sends_a_malformed_id_to_stripe() -> None:
    seen: list[httpx.Request] = []
    stripe = client_for(lambda r: httpx.Response(200, json={}), seen)

    assert await stripe.get_price("../customers") is None
    assert seen == []
