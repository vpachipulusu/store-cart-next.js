"""The per-store cart creation cap against real store databases (KAN-252).

Over the cap the API answers 429 and creates no cart row; carts that already exist keep working;
one store's cap is not another's; with the limiter down, creation is refused (503) while existing
carts are untouched. Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

import dataclasses
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api import store_db
from app.api.deps import get_rate_limiter
from app.core.rate_limit import CART_CREATE_POLICY
from tests.api.products_support import world  # noqa: F401  (fixture)
from tests.api.test_cart_e2e import (
    NORTH_A,
    NORTH_B,
    add,
    cart_count,
    data_of,
    read,
    sellable_variant,
)
from tests.fakes import FakeRateLimiter, RaisingRateLimiter
from tests.isolation_world import World, header_identity_app, make_client
from tests.pg_scaffold import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"),
    pytest.mark.asyncio(loop_scope="module"),
]

CAP = 2


@pytest.fixture(autouse=True)
def small_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        store_db,
        "CART_CREATE_POLICY",
        dataclasses.replace(CART_CREATE_POLICY, limit=CAP),
    )


async def client_with(
    world: World, limiter: FakeRateLimiter | RaisingRateLimiter
) -> AsyncIterator[AsyncClient]:
    app = header_identity_app(world)
    async with make_client(app) as http:
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
        yield http


@pytest_asyncio.fixture(loop_scope="module")
async def limited(world: World) -> AsyncIterator[AsyncClient]:
    async for http in client_with(world, FakeRateLimiter()):
        yield http


@pytest_asyncio.fixture(loop_scope="module")
async def limiter_down(world: World) -> AsyncIterator[AsyncClient]:
    async for http in client_with(world, RaisingRateLimiter()):
        yield http


async def test_creation_over_the_cap_is_429_and_creates_no_cart(
    limited: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(limited, world)
    before = await cart_count(world)
    for _ in range(CAP):
        data_of(await add(limited, variant))

    refused = await add(limited, variant)

    assert refused.status_code == 429
    assert refused.json() == {"success": False, "error": "Too many requests"}
    assert int(refused.headers["Retry-After"]) >= 1
    assert await cart_count(world) == before + CAP


async def test_existing_carts_keep_working_when_the_cap_is_used_up(
    limited: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(limited, world)
    token = data_of(await add(limited, variant))["cart_token"]
    data_of(await add(limited, variant))  # second creation: the cap is now used up
    assert (await add(limited, variant)).status_code == 429

    again = data_of(await add(limited, variant, 2, token=token))
    shown = await read(limited, token)

    assert again["lines"][0]["quantity"] == 3
    assert shown["lines"][0]["quantity"] == 3


async def test_another_stores_cap_is_separate(
    limited: AsyncClient, world: World
) -> None:
    variant_a = await sellable_variant(limited, world)
    variant_b = await sellable_variant(
        limited, world, store=("b", "north"), owner="bob"
    )
    for _ in range(CAP):
        data_of(await add(limited, variant_a))
    assert (await add(limited, variant_a)).status_code == 429

    other = data_of(await add(limited, variant_b, slug=NORTH_B))

    assert other["cart_token"] is not None
    assert NORTH_A != NORTH_B


async def test_a_request_that_would_not_create_a_cart_does_not_spend_the_cap(
    limited: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(limited, world, stock=1)
    for _ in range(CAP * 2):
        assert (await add(limited, variant, 5)).status_code == 409
        assert (await add(limited, "no-such-variant")).status_code == 404

    created = await add(limited, variant, 1)

    assert created.status_code == 200


async def test_with_the_limiter_down_creation_is_refused_but_carts_keep_working(
    limiter_down: AsyncClient, limited: AsyncClient, world: World
) -> None:
    variant = await sellable_variant(limited, world)
    token = data_of(await add(limited, variant))["cart_token"]
    before = await cart_count(world)

    refused = await add(limiter_down, variant)
    existing = data_of(await add(limiter_down, variant, 1, token=token))

    assert refused.status_code == 503
    assert refused.headers["Retry-After"] == "5"
    assert await cart_count(world) == before
    assert existing["lines"][0]["quantity"] == 2
