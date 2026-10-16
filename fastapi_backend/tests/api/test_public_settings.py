"""GET /v1/settings/currency (KAN-205): the platform currency and nothing else.

The repository is a fake; the route, service, headers and rate limit are real.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.api.deps import get_rate_limiter
from app.api.v1.settings import CurrencyData, get_settings_service
from app.core.rate_limit import PUBLIC_SETTINGS_POLICY
from app.main import create_app
from app.services.public_settings import PublicSettingsService
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
CACHE = "private, max-age=60, stale-while-revalidate=300"


class FakeSettings:
    """Holds every app setting; the service must ask only for ``currency``."""

    def __init__(self, **values: Any) -> None:
        self._values = values
        self.reads: list[str] = []

    async def get_value(self, key: str) -> object | None:
        self.reads.append(key)
        return self._values.get(key)


def build(
    repo: FakeSettings, limiter: FakeRateLimiter | RaisingRateLimiter | None = None
) -> tuple[AsyncClient, FakeRateLimiter | RaisingRateLimiter]:
    limiter = limiter or FakeRateLimiter()
    app = create_app()
    app.dependency_overrides[get_settings_service] = lambda: PublicSettingsService(repo)
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )
    return client, limiter


async def fetch_currency(repo: FakeSettings) -> Response:
    http, _ = build(repo)
    async with http:
        return await http.get("/v1/settings/currency")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    http, _ = build(FakeSettings(currency="EUR", secret_key="s3cret"))
    async with http:
        yield http


async def test_set_currency_is_returned() -> None:
    response = await fetch_currency(FakeSettings(currency="EUR"))

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"currency": "EUR"}}


async def test_stored_code_is_matched_case_insensitively_and_canonical() -> None:
    response = await fetch_currency(FakeSettings(currency=" gbp "))

    assert response.json()["data"] == {"currency": "GBP"}


async def test_unset_currency_falls_back_to_the_frontend_default() -> None:
    response = await fetch_currency(FakeSettings())

    assert response.status_code == 200
    assert response.json()["data"] == {"currency": "USD"}


@pytest.mark.parametrize(
    "stored", ["XYZ", "", "   ", "dollars", 42, None, ["EUR"], {"code": "EUR"}, True]
)
async def test_unknown_or_malformed_value_falls_back_to_the_default(
    stored: Any,
) -> None:
    response = await fetch_currency(FakeSettings(currency=stored))

    assert response.status_code == 200
    assert response.json()["data"] == {"currency": "USD"}


async def test_only_the_currency_setting_is_read() -> None:
    repo = FakeSettings(currency="EUR", secret_key="s3cret", app_name="Secret Co")

    response = await fetch_currency(repo)

    assert repo.reads == ["currency"]
    assert "s3cret" not in response.text
    assert "Secret Co" not in response.text


async def test_response_exposes_only_the_currency_field(client: AsyncClient) -> None:
    response = await client.get("/v1/settings/currency")

    assert set(response.json()) == {"success", "data"}
    assert set(response.json()["data"]) == {"currency"}
    assert set(CurrencyData.model_fields) == {"currency"}


async def test_response_is_cacheable_with_a_short_max_age(client: AsyncClient) -> None:
    response = await client.get("/v1/settings/currency")

    assert response.headers["Cache-Control"] == CACHE
    assert response.headers["ETag"].startswith('"')


async def test_matching_if_none_match_returns_304(client: AsyncClient) -> None:
    first = await client.get("/v1/settings/currency")

    second = await client.get(
        "/v1/settings/currency", headers={"If-None-Match": first.headers["ETag"]}
    )

    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["Cache-Control"] == CACHE


@pytest.mark.parametrize("template", ["W/{}", '{}, "other"', "*"])
async def test_if_none_match_accepts_weak_lists_and_wildcard(
    client: AsyncClient, template: str
) -> None:
    first = await client.get("/v1/settings/currency")

    second = await client.get(
        "/v1/settings/currency",
        headers={"If-None-Match": template.format(first.headers["ETag"])},
    )

    assert second.status_code == 304


async def test_stale_if_none_match_returns_the_full_response(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/v1/settings/currency", headers={"If-None-Match": '"stale"'}
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"currency": "EUR"}


async def test_etag_changes_when_the_currency_changes() -> None:
    first = await fetch_currency(FakeSettings(currency="EUR"))
    second = await fetch_currency(FakeSettings(currency="GBP"))

    assert first.headers["ETag"] != second.headers["ETag"]


async def test_requires_the_internal_key() -> None:
    http, _ = build(FakeSettings())

    async with http:
        missing = await http.get(
            "/v1/settings/currency", headers={"X-Internal-Key": ""}
        )
        wrong = await http.get("/v1/settings/currency", headers={"X-Internal-Key": "x"})

    assert missing.status_code == wrong.status_code == 401


async def test_rate_limit_is_keyed_by_the_forwarded_client_ip() -> None:
    http, limiter = build(FakeSettings())

    async with http:
        await http.get("/v1/settings/currency", headers={"X-Client-IP": "203.0.113.7"})

    assert isinstance(limiter, FakeRateLimiter)
    assert limiter.hits == [("public_settings:ip:203.0.113.7", PUBLIC_SETTINGS_POLICY)]


async def test_requests_over_the_limit_get_429_and_no_cache_header() -> None:
    http, _ = build(FakeSettings())

    async with http:
        responses = [
            await http.get("/v1/settings/currency")
            for _ in range(PUBLIC_SETTINGS_POLICY.limit + 1)
        ]

    assert responses[-1].status_code == 429
    assert "Cache-Control" not in responses[-1].headers
    assert "Retry-After" in responses[-1].headers


async def test_rate_limiter_outage_fails_open() -> None:
    http, _ = build(FakeSettings(), RaisingRateLimiter())

    async with http:
        response = await http.get("/v1/settings/currency")

    assert response.status_code == 200


class BrokenSettings:
    async def get_value(self, key: str) -> object | None:
        raise RuntimeError("database is down")


async def test_database_error_is_an_uncached_500() -> None:
    app = create_app()
    app.dependency_overrides[get_settings_service] = lambda: PublicSettingsService(
        BrokenSettings()
    )
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(FakeRateLimiter())
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        response = await http.get("/v1/settings/currency")

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "Internal server error"}
    assert "Cache-Control" not in response.headers
    assert "ETag" not in response.headers
