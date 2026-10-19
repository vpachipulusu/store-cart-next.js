"""Checkout route without a database (KAN-68): error mapping, no-store and Stripe config.

The checkout service is a stub injected through ``dependency_overrides``; the router, the
internal-key check and the request validation are real.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_rate_limiter
from app.api.v1.checkout import get_checkout_service
from app.core.config import settings
from app.main import create_app
from app.services.store_checkout import (
    CartNotReady,
    CheckoutStarted,
    CheckoutStoreNotFound,
    CheckoutUnavailable,
    InvalidCheckoutUrl,
    PaymentsNotEnabled,
)
from app.services.store_sessions import StoreDatabaseUnavailable
from tests.fakes import FakeRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
URL = "/v1/storefront/acme/checkout"
BODY = {
    "success_url": "https://acme.example.com/ok",
    "cancel_url": "https://acme.example.com/cart",
}


class StubCheckout:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    async def start(
        self, slug: str, token: str | None, success_url: str, cancel_url: str
    ) -> CheckoutStarted:
        self.calls.append((slug, token))
        if self.error is not None:
            raise self.error
        return CheckoutStarted("order1", "https://checkout.stripe.com/c/pay/cs_1")


def client_for(stub: StubCheckout | None = None, *, key: str = KEY) -> AsyncClient:
    app = create_app()
    if stub is not None:
        app.dependency_overrides[get_checkout_service] = lambda: stub
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(FakeRateLimiter())
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": key},
    )


async def test_start_returns_the_checkout_url_and_is_never_cached() -> None:
    stub = StubCheckout()
    async with client_for(stub) as client:
        response = await client.post(URL, json=BODY, headers={"X-Cart-Token": "t"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "success": True,
        "data": {
            "order_id": "order1",
            "checkout_url": "https://checkout.stripe.com/c/pay/cs_1",
        },
    }
    assert stub.calls == [("acme", "t")]


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (CheckoutStoreNotFound(), 404, "Store not found"),
        (PaymentsNotEnabled(), 409, "Payments are not enabled for this store"),
        (CartNotReady("Your cart has changed."), 409, "Your cart has changed."),
        (InvalidCheckoutUrl(), 422, "Return URL is not allowed"),
        (CheckoutUnavailable(), 502, "Payment could not be started. Try again."),
        (StoreDatabaseUnavailable("s1"), 503, "Store database is not available"),
    ],
)
async def test_checkout_errors_map_to_their_status_and_are_never_cached(
    error: Exception, status: int, message: str
) -> None:
    async with client_for(StubCheckout(error)) as client:
        response = await client.post(URL, json=BODY)

    assert response.status_code == status
    assert response.json() == {"success": False, "error": message}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "total_minor": 1},
        {**BODY, "line_items": [{"price": 1}]},
        {"success_url": BODY["success_url"]},
    ],
)
async def test_only_the_return_urls_are_accepted(body: dict[str, object]) -> None:
    stub = StubCheckout()
    async with client_for(stub) as client:
        response = await client.post(URL, json=body)

    assert response.status_code == 422
    assert stub.calls == []


async def test_missing_stripe_key_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    async with client_for() as client:
        response = await client.post(URL, json=BODY)

    assert response.status_code == 503
    assert response.json()["error"] == "Payments are not available right now"


async def test_the_internal_key_is_required() -> None:
    stub = StubCheckout()
    async with client_for(stub, key="wrong") as client:
        response = await client.post(URL, json=BODY)

    assert response.status_code == 401
    assert stub.calls == []
