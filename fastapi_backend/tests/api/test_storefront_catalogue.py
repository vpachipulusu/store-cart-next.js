"""Public catalogue routes without a database (KAN-75): field allowlist, error mapping,
internal key and no-store on every answer.

The catalogue service is a stub injected through ``dependency_overrides``; the router, the
internal-key check and the request validation are real.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_rate_limiter
from app.api.store_db import STORE_UNAVAILABLE, storefront_catalogue_service
from app.core.rate_limit import STOREFRONT_CATALOGUE_POLICY
from app.main import create_app
from app.services.store_product_types import OptionRecord, OptionValueRecord
from app.services.store_sessions import StoreDatabaseUnavailable
from app.services.storefront_catalogue import (
    InvalidStorefrontQuery,
    PublicCategory,
    PublicImage,
    PublicProduct,
    PublicProductPage,
    PublicProductSummary,
    PublicVariant,
    StorefrontNotFound,
)
from tests.fakes import FakeRateLimiter, FakeSession, FakeSessionProvider, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
IMAGE = PublicImage("https://img.example.test/stores/s1/a.jpg", "Front")
TOPS = PublicCategory(name="Tops", slug="tops", parent_slug="clothing")
PRODUCT = PublicProduct(
    title="Tee",
    slug="tee",
    description="Soft",
    currency="GBP",
    options=(
        OptionRecord(
            id="o1", name="Size", position=0, values=(OptionValueRecord("v1", "S", 0),)
        ),
    ),
    variants=(PublicVariant("var1", 1200, 1500, True, ("v1",)),),
    images=(IMAGE,),
    categories=(TOPS,),
)


class StubCatalogue:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def list_products(self, **kwargs: Any) -> PublicProductPage:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        item = PublicProductSummary("Tee", "tee", 1200, 1500, IMAGE)
        return PublicProductPage((item,), "GBP", 1, kwargs["limit"], kwargs["offset"])

    async def get_product(self, slug: str) -> PublicProduct:
        if self.error is not None:
            raise self.error
        return PRODUCT

    async def list_categories(self) -> tuple[PublicCategory, ...]:
        return (TOPS,)


def client_for(
    stub: StubCatalogue,
    key: str | None = KEY,
    limiter: FakeRateLimiter | None = None,
) -> AsyncClient:
    app = create_app()

    async def service() -> AsyncIterator[StubCatalogue]:
        yield stub

    app.dependency_overrides[storefront_catalogue_service] = service
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        limiter or FakeRateLimiter()
    )
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": key} if key else {},
    )


async def test_the_listing_has_only_public_fields_and_is_never_cached() -> None:
    stub = StubCatalogue()
    async with client_for(stub) as client:
        response = await client.get(
            "/v1/storefront/acme/products",
            params={"category": "tops", "q": "tee", "limit": 12, "offset": 24},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body == {
        "data": [
            {
                "title": "Tee",
                "slug": "tee",
                "min_price_minor": 1200,
                "max_price_minor": 1500,
                "image": {"url": IMAGE.url, "alt_text": "Front"},
            }
        ],
        "currency": "GBP",
        "total": 1,
        "limit": 12,
        "offset": 24,
    }
    assert stub.calls == [
        {"category_slug": "tops", "query": "tee", "limit": 12, "offset": 24}
    ]


async def test_a_product_has_only_public_fields() -> None:
    async with client_for(StubCatalogue()) as client:
        response = await client.get("/v1/storefront/acme/products/tee")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"] == {
        "title": "Tee",
        "slug": "tee",
        "description": "Soft",
        "currency": "GBP",
        "options": [{"name": "Size", "values": [{"id": "v1", "value": "S"}]}],
        "variants": [
            {
                "id": "var1",
                "price_minor": 1200,
                "compare_at_price_minor": 1500,
                "in_stock": True,
                "option_value_ids": ["v1"],
            }
        ],
        "images": [{"url": IMAGE.url, "alt_text": "Front"}],
        "categories": [{"name": "Tops", "slug": "tops", "parent_slug": "clothing"}],
    }


async def test_categories_are_listed() -> None:
    async with client_for(StubCatalogue()) as client:
        response = await client.get("/v1/storefront/acme/categories")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "success": True,
        "data": [{"name": "Tops", "slug": "tops", "parent_slug": "clothing"}],
    }


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (StorefrontNotFound("Product not found"), 404, "Product not found"),
        (
            InvalidStorefrontQuery("Search text is too long"),
            422,
            "Search text is too long",
        ),
    ],
)
async def test_errors_map_to_their_status_and_are_never_cached(
    error: Exception, status: int, message: str
) -> None:
    async with client_for(StubCatalogue(error)) as client:
        listed = await client.get("/v1/storefront/acme/products")
        read = await client.get("/v1/storefront/acme/products/tee")

    for response in (listed, read):
        assert response.status_code == status
        assert response.json() == {"success": False, "error": message}
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"category": "x" * 201},
        {"q": "x" * 401},
    ],
)
async def test_out_of_range_query_parameters_are_rejected(
    params: dict[str, Any],
) -> None:
    async with client_for(StubCatalogue()) as client:
        response = await client.get("/v1/storefront/acme/products", params=params)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/v1/storefront/acme/products",
        "/v1/storefront/acme/products/tee",
        "/v1/storefront/acme/categories",
    ],
)
async def test_every_route_needs_the_internal_key(path: str) -> None:
    async with client_for(StubCatalogue(), key=None) as client:
        response = await client.get(path)

    assert response.status_code == 401


async def test_search_text_too_long_for_the_service_is_its_422() -> None:
    error = InvalidStorefrontQuery("Search text is at most 100 characters")
    async with client_for(StubCatalogue(error)) as client:
        response = await client.get(
            "/v1/storefront/acme/products", params={"q": "x" * 150}
        )

    assert response.status_code == 422
    assert response.json() == {
        "success": False,
        "error": "Search text is at most 100 characters",
    }


async def test_requests_over_the_storefront_limit_get_429() -> None:
    limiter = FakeRateLimiter()
    async with client_for(StubCatalogue(), limiter=limiter) as client:
        statuses = [
            (await client.get("/v1/storefront/acme/categories")).status_code
            for _ in range(STOREFRONT_CATALOGUE_POLICY.limit + 1)
        ]

    assert statuses[-1] == 429
    assert all(policy is STOREFRONT_CATALOGUE_POLICY for _, policy in limiter.hits)


async def _first(slug: str) -> object:
    provider = FakeSessionProvider(FakeSession())
    agen = storefront_catalogue_service(slug, provider)  # type: ignore[arg-type]
    return await agen.__anext__()


async def test_an_unknown_store_is_the_lookup_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_store(repository: object, slug: str) -> None:
        return None

    monkeypatch.setattr("app.api.store_db.active_store_id", no_store)

    with pytest.raises(HTTPException) as raised:
        await _first("acme")

    assert raised.value.status_code == 404
    assert raised.value.detail == "Store not found"
    assert raised.value.headers == {"Cache-Control": "no-store"}


async def test_an_unusable_store_database_is_a_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def found(repository: object, slug: str) -> str:
        return "store1"

    async def currency(self: object) -> str:
        return "GBP"

    @asynccontextmanager
    async def failing(store_id: str, provider: object) -> AsyncIterator[None]:
        raise StoreDatabaseUnavailable(store_id)
        yield

    monkeypatch.setattr("app.api.store_db.active_store_id", found)
    monkeypatch.setattr("app.api.store_db.PublicSettingsService.currency", currency)
    monkeypatch.setattr("app.api.store_db.open_store_session", failing)

    with pytest.raises(HTTPException) as raised:
        await _first("acme")

    assert raised.value.status_code == 503
    assert raised.value.detail == STORE_UNAVAILABLE
    assert raised.value.headers == {"Cache-Control": "no-store"}


async def test_a_forwarded_visitor_is_limited_by_ip_and_a_shared_read_by_store() -> (
    None
):
    limiter = FakeRateLimiter()
    async with client_for(StubCatalogue(), limiter=limiter) as client:
        await client.get(
            "/v1/storefront/acme/categories", headers={"X-Client-IP": "203.0.113.9"}
        )
        await client.get("/v1/storefront/acme/categories")
        await client.get("/v1/storefront/other/products")
        await client.get(
            "/v1/storefront/acme/categories", headers={"X-Client-IP": "not-an-ip"}
        )

    assert [identifier for identifier, _ in limiter.hits] == [
        "storefront_catalogue:ip:203.0.113.9",
        "storefront_catalogue:store:acme",
        "storefront_catalogue:store:other",
        "storefront_catalogue:store:acme",
    ]
