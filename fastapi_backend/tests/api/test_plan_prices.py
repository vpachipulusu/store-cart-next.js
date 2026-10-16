"""GET /v1/settings/plan-prices (KAN-208): internal key only, no session, no secrets."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_rate_limiter
from app.api.v1.settings import get_plan_prices_service
from app.core.rate_limit import PUBLIC_SETTINGS_POLICY
from app.main import create_app
from app.services.plan_prices import PlanPrices, TierPrices
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
PRICES = PlanPrices(TierPrices(1900, 19000), TierPrices(9900, None))


class FakeService:
    def __init__(self, prices: PlanPrices = PRICES) -> None:
        self.prices_result = prices
        self.calls = 0

    async def prices(self) -> PlanPrices:
        self.calls += 1
        return self.prices_result


def build(
    service: FakeService, limiter: FakeRateLimiter | RaisingRateLimiter | None = None
) -> tuple[AsyncClient, FakeRateLimiter | RaisingRateLimiter]:
    limiter = limiter or FakeRateLimiter()
    app = create_app()
    app.dependency_overrides[get_plan_prices_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )
    return client, limiter


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    http, _ = build(FakeService())
    async with http:
        yield http


async def test_returns_minor_unit_prices_per_tier(client: AsyncClient) -> None:
    response = await client.get("/v1/settings/plan-prices")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "pro": {"monthly": 1900, "yearly": 19000},
            "enterprise": {"monthly": 9900, "yearly": None},
        },
    }


async def test_is_privately_cacheable(client: AsyncClient) -> None:
    response = await client.get("/v1/settings/plan-prices")

    assert response.headers["Cache-Control"] == "private, max-age=300"


async def test_requires_the_internal_key_and_no_session() -> None:
    service = FakeService()
    http, _ = build(service)

    async with http:
        bad = await http.get(
            "/v1/settings/plan-prices", headers={"X-Internal-Key": "x"}
        )
        good = await http.get("/v1/settings/plan-prices")

    assert bad.status_code == 401 and service.calls == 1
    assert good.status_code == 200


async def test_rate_limit_is_keyed_by_the_client_ip() -> None:
    http, limiter = build(FakeService())

    async with http:
        await http.get(
            "/v1/settings/plan-prices", headers={"X-Client-IP": "203.0.113.9"}
        )

    assert isinstance(limiter, FakeRateLimiter)
    assert limiter.hits == [("public_settings:ip:203.0.113.9", PUBLIC_SETTINGS_POLICY)]


async def test_requests_over_the_limit_get_429_without_cache_header() -> None:
    http, _ = build(FakeService())

    async with http:
        last = None
        for _ in range(PUBLIC_SETTINGS_POLICY.limit + 1):
            last = await http.get("/v1/settings/plan-prices")

    assert last is not None and last.status_code == 429
    assert "Cache-Control" not in last.headers


async def test_limiter_outage_fails_open() -> None:
    http, _ = build(FakeService(), RaisingRateLimiter())

    async with http:
        response = await http.get("/v1/settings/plan-prices")

    assert response.status_code == 200


def test_service_factory_maps_each_setting_to_its_tier_and_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import settings as routes
    from app.core.config import settings

    for name, value in {
        "STRIPE_PRICE_ID_PRO_MONTHLY": "price_pm",
        "STRIPE_PRICE_ID_PRO_YEARLY": "price_py",
        "STRIPE_PRICE_ID_ENTERPRISE_MONTHLY": "price_em",
        "STRIPE_PRICE_ID_ENTERPRISE_YEARLY": None,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(routes, "get_stripe_prices", lambda: None)

    service = routes.get_plan_prices_service()

    assert service._price_ids == {
        ("pro", "monthly"): "price_pm",
        ("pro", "yearly"): "price_py",
        ("enterprise", "monthly"): "price_em",
        ("enterprise", "yearly"): "",
    }


async def test_factory_without_stripe_gives_all_null_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import settings as routes

    monkeypatch.setattr(routes, "get_stripe_prices", lambda: None)

    prices = await routes.get_plan_prices_service().prices()

    assert prices == PlanPrices(TierPrices(None, None), TierPrices(None, None))
