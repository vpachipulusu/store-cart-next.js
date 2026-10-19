"""GET /v1/storefront/{slug} (KAN-65): public fields only, cacheable, one answer for "no".

The repository is a fake; the route, service, slug rules, rate limit and headers are real.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.api.deps import get_rate_limiter
from app.api.v1.storefront import StorefrontData, get_storefront_service
from app.core.rate_limit import STOREFRONT_POLICY
from app.main import create_app
from app.repositories.storefront import PublicStore
from app.services.storefront import StorefrontService
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
ACME = PublicStore(name="Acme Shop", slug="acme")
NOT_FOUND_BODY = {"success": False, "error": "Store not found"}
SUCCESS_CACHE = "public, max-age=60, stale-while-revalidate=300"
MISS_CACHE = "public, max-age=30"


class FakeStorefronts:
    """Returns only ACTIVE stores, as the real query does; records every lookup."""

    def __init__(self, *stores: PublicStore) -> None:
        self._stores = {store.slug: store for store in stores}
        self.lookups: list[str] = []

    async def find_active_by_slug(self, slug: str) -> PublicStore | None:
        self.lookups.append(slug)
        return self._stores.get(slug)


def build(
    repo: FakeStorefronts, limiter: FakeRateLimiter | RaisingRateLimiter | None = None
) -> tuple[AsyncClient, FakeRateLimiter | RaisingRateLimiter]:
    limiter = limiter or FakeRateLimiter()
    app = create_app()
    app.dependency_overrides[get_storefront_service] = lambda: StorefrontService(repo)
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )
    return client, limiter


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    http, _ = build(FakeStorefronts(ACME))
    async with http:
        yield http


async def test_returns_public_details_of_an_active_store(client: AsyncClient) -> None:
    response = await client.get("/v1/storefront/acme")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"name": "Acme Shop", "slug": "acme"},
    }


async def test_response_exposes_only_the_allowlisted_fields(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/storefront/acme")

    assert set(response.json()["data"]) == {"name", "slug"}
    assert set(response.json()) == {"success", "data"}


def test_public_schema_declares_only_the_allowlisted_fields() -> None:
    assert set(StorefrontData.model_fields) == {"name", "slug"}


async def test_success_is_cacheable_and_has_an_etag(client: AsyncClient) -> None:
    response = await client.get("/v1/storefront/acme")

    assert response.headers["Cache-Control"] == SUCCESS_CACHE
    assert response.headers["ETag"].startswith('"')
    assert response.headers["ETag"].endswith('"')


async def test_matching_if_none_match_returns_304_without_a_body(
    client: AsyncClient,
) -> None:
    first = await client.get("/v1/storefront/acme")

    second = await client.get(
        "/v1/storefront/acme", headers={"If-None-Match": first.headers["ETag"]}
    )

    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["ETag"] == first.headers["ETag"]
    assert second.headers["Cache-Control"] == SUCCESS_CACHE


@pytest.mark.parametrize("template", ["W/{}", '{}, "other"', "*"])
async def test_if_none_match_accepts_weak_lists_and_wildcard(
    client: AsyncClient, template: str
) -> None:
    first = await client.get("/v1/storefront/acme")

    second = await client.get(
        "/v1/storefront/acme",
        headers={"If-None-Match": template.format(first.headers["ETag"])},
    )

    assert second.status_code == 304


async def test_stale_if_none_match_returns_the_full_response(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/v1/storefront/acme", headers={"If-None-Match": '"stale"'}
    )

    assert response.status_code == 200
    assert response.json()["data"]["slug"] == "acme"


async def test_etag_changes_when_the_public_details_change() -> None:
    first_client, _ = build(FakeStorefronts(ACME))
    second_client, _ = build(FakeStorefronts(PublicStore(name="Renamed", slug="acme")))

    async with first_client, second_client:
        first = await first_client.get("/v1/storefront/acme")
        second = await second_client.get("/v1/storefront/acme")

    assert first.headers["ETag"] != second.headers["ETag"]


async def test_slug_is_matched_case_insensitively_and_returned_canonical(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/storefront/ACME")

    assert response.status_code == 200
    assert response.json()["data"]["slug"] == "acme"


async def test_unknown_slug_is_404_with_a_short_public_cache(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/storefront/nope-shop")

    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY
    assert response.headers["Cache-Control"] == MISS_CACHE


@pytest.mark.parametrize(
    "slug",
    [
        "ab",  # too short
        "a" * 64,  # too long
        "-acme",
        "acme-",
        "ac--me",
        "ac_me",
        "ac.me",
        "acm%C3%A9",
        "www",  # reserved
        "admin",
        "a%20b",
    ],
)
async def test_invalid_or_reserved_slugs_are_the_same_404_without_a_lookup(
    slug: str,
) -> None:
    repo = FakeStorefronts(ACME)
    http, _ = build(repo)

    async with http:
        response = await http.get(f"/v1/storefront/{slug}")
        unknown = await http.get("/v1/storefront/nope-shop")

    assert response.status_code == 404
    assert response.content == unknown.content
    assert response.headers["Cache-Control"] == unknown.headers["Cache-Control"]
    assert repo.lookups == ["nope-shop"]


async def test_non_active_and_unknown_stores_are_indistinguishable() -> None:
    # The repository returns None for every non-ACTIVE status, so the route cannot tell a
    # suspended store from one that never existed (the real query is covered end to end).
    http, _ = build(FakeStorefronts())

    async with http:
        suspended = await http.get("/v1/storefront/suspended-shop")
        unknown = await http.get("/v1/storefront/never-existed")

    assert suspended.status_code == unknown.status_code == 404
    assert suspended.content == unknown.content
    assert suspended.headers.keys() == unknown.headers.keys()
    assert suspended.headers["Cache-Control"] == unknown.headers["Cache-Control"]
    assert "ETag" not in suspended.headers


async def test_requires_the_internal_key() -> None:
    http, _ = build(FakeStorefronts(ACME))

    async with http:
        missing = await http.get("/v1/storefront/acme", headers={"X-Internal-Key": ""})
        wrong = await http.get("/v1/storefront/acme", headers={"X-Internal-Key": "x"})

    assert missing.status_code == wrong.status_code == 401


async def test_rate_limit_is_keyed_by_the_forwarded_client_ip() -> None:
    http, limiter = build(FakeStorefronts(ACME))

    async with http:
        await http.get("/v1/storefront/acme", headers={"X-Client-IP": "203.0.113.7"})

    assert isinstance(limiter, FakeRateLimiter)
    assert limiter.hits == [("storefront:ip:203.0.113.7", STOREFRONT_POLICY)]


async def test_requests_over_the_limit_get_429_and_no_cache_header() -> None:
    http, _ = build(FakeStorefronts(ACME))

    async with http:
        responses: list[Response] = [
            await http.get("/v1/storefront/acme")
            for _ in range(STOREFRONT_POLICY.limit + 1)
        ]

    assert [r.status_code for r in responses[:-1]] == [200] * STOREFRONT_POLICY.limit
    assert responses[-1].status_code == 429
    assert "Cache-Control" not in responses[-1].headers
    assert "Retry-After" in responses[-1].headers


async def test_rate_limiter_outage_fails_open() -> None:
    http, _ = build(FakeStorefronts(ACME), RaisingRateLimiter())

    async with http:
        response = await http.get("/v1/storefront/acme")

    assert response.status_code == 200


async def test_response_carries_no_rate_limit_headers_into_shared_caches(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/storefront/acme")

    assert not [h for h in response.headers if h.lower().startswith("x-ratelimit")]


async def test_a_shared_lookup_without_a_visitor_ip_is_limited_per_store() -> None:
    """KAN-75: cached server lookups for one slug cannot fill another store's bucket."""
    http, limiter = build(FakeStorefronts(ACME))

    async with http:
        await http.get("/v1/storefront/acme")
        await http.get("/v1/storefront/ghost-shop")

    assert isinstance(limiter, FakeRateLimiter)
    assert [identifier for identifier, _ in limiter.hits] == [
        "storefront:store:acme",
        "storefront:store:ghost-shop",
    ]
