"""Checkout fails closed when the rate limiter is down (KAN-256).

Every checkout call writes an order and calls Stripe, so a Redis outage must not lift the
limit: the route answers 503 and never reaches the service.
"""

from httpx import ASGITransport, AsyncClient

from app.api.deps import get_rate_limiter
from app.api.v1.checkout import get_checkout_service
from app.core.rate_limit import CHECKOUT_POLICY
from app.main import create_app
from app.services.store_checkout import CheckoutStarted
from tests.fakes import RaisingRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
URL = "/v1/storefront/acme/checkout"
BODY = {
    "success_url": "https://acme.example.com/ok",
    "cancel_url": "https://acme.example.com/cart",
}


class CountingCheckout:
    def __init__(self) -> None:
        self.calls = 0

    async def start(
        self, slug: str, token: str | None, success_url: str, cancel_url: str
    ) -> CheckoutStarted:
        self.calls += 1
        return CheckoutStarted("order1", "https://checkout.stripe.com/c/pay/cs_1")


def test_the_checkout_policy_fails_closed() -> None:
    assert CHECKOUT_POLICY.fail_closed is True


async def test_a_rate_limiter_outage_is_503_and_starts_no_checkout() -> None:
    app = create_app()
    service = CountingCheckout()
    app.dependency_overrides[get_checkout_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        RaisingRateLimiter()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    ) as client:
        response = await client.post(URL, json=BODY, headers={"X-Cart-Token": "t"})

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "error": "Service temporarily unavailable",
    }
    assert service.calls == 0
