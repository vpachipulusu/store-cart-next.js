"""Cart routes without a database (KAN-76): error mapping and no-store on every answer.

The cart service is a stub injected through ``dependency_overrides``; the router, the
internal-key check and the request validation are real.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_rate_limiter
from app.api.store_db import storefront_cart_service
from app.main import create_app
from app.services.store_cart import CartConflict, CartView, ItemUnavailable
from app.services.store_cart_limits import (
    CartCreationLimited,
    CartCreationUnavailable,
)
from app.services.store_totals import Totals
from tests.fakes import FakeRateLimiter, as_limiter

KEY = "test-only-internal-service-key-not-for-deployment"
EMPTY = CartView(lines=(), totals=Totals(0, 0, 0, 0, False), can_checkout=False)


class StubCart:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def view(self, token: str | None) -> CartView:
        return EMPTY

    async def add_item(
        self, token: str | None, variant_id: str, quantity: int
    ) -> CartView:
        if self.error is not None:
            raise self.error
        return EMPTY

    async def set_quantity(
        self, token: str | None, variant_id: str, quantity: int
    ) -> CartView:
        return await self.add_item(token, variant_id, quantity)

    async def remove_item(self, token: str | None, variant_id: str) -> CartView:
        return EMPTY


def client_for(stub: StubCart) -> AsyncClient:
    app = create_app()

    async def service() -> AsyncIterator[StubCart]:
        yield stub

    app.dependency_overrides[storefront_cart_service] = service
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(FakeRateLimiter())
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (ItemUnavailable(), 404, "That item is not available"),
        (CartConflict("Only 3 in stock"), 409, "Only 3 in stock"),
    ],
)
async def test_cart_errors_map_to_their_status_and_are_never_cached(
    error: Exception, status: int, message: str
) -> None:
    async with client_for(StubCart(error)) as client:
        added = await client.post(
            "/v1/storefront/acme/cart/items", json={"variant_id": "v1", "quantity": 1}
        )
        put = await client.put(
            "/v1/storefront/acme/cart/items/v1", json={"quantity": 1}
        )

    for response in (added, put):
        assert response.status_code == status
        assert response.json() == {"success": False, "error": message}
        assert response.headers["cache-control"] == "no-store"


async def test_a_read_is_never_cached_and_carries_no_token() -> None:
    async with client_for(StubCart()) as client:
        response = await client.get("/v1/storefront/acme/cart")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["cart_token"] is None


@pytest.mark.parametrize("variant_id", ["%2E%2E", "a.b", "a b", "x" * 101])
async def test_a_variant_id_outside_the_id_alphabet_is_rejected(
    variant_id: str,
) -> None:
    async with client_for(StubCart()) as client:
        put = await client.put(
            f"/v1/storefront/acme/cart/items/{variant_id}", json={"quantity": 1}
        )
        added = await client.post(
            "/v1/storefront/acme/cart/items",
            json={"variant_id": variant_id.replace("%2E", "."), "quantity": 1},
        )

    assert put.status_code in (404, 422)
    assert added.status_code == 422


async def test_a_refused_creation_is_429_with_retry_after_and_never_cached() -> None:
    error = CartCreationLimited(retry_after_seconds=42)
    async with client_for(StubCart(error)) as client:
        response = await client.post(
            "/v1/storefront/acme/cart/items", json={"variant_id": "v1", "quantity": 1}
        )

    assert response.status_code == 429
    assert response.json() == {"success": False, "error": "Too many requests"}
    assert response.headers["Retry-After"] == "42"
    assert response.headers["Cache-Control"] == "no-store"


async def test_creation_with_the_limiter_down_is_503_with_retry_after() -> None:
    async with client_for(StubCart(CartCreationUnavailable())) as client:
        response = await client.put(
            "/v1/storefront/acme/cart/items/v1", json={"quantity": 1}
        )

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "error": "Service temporarily unavailable",
    }
    assert response.headers["Retry-After"] == "5"
    assert response.headers["Cache-Control"] == "no-store"
