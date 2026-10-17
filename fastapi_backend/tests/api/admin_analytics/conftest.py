"""Fixtures for the admin analytics e2e tests (KAN-119): real Postgres, fake Firebase and Stripe.

Same contract as ``tests/api/admin_subscriptions``: runs only when ``TEST_DATABASE_URL``
points at a throwaway local ``*_test`` database, rebuilt with the real Alembic migrations.
Only Firebase and Stripe (price reads and the subscription list) are replaced.
"""

import time
from collections.abc import AsyncIterator, Iterator
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.auth import get_session_identity
from app.api.deps import get_session_provider
from app.api.v1.admin_analytics import stripe_lister, stripe_prices
from app.core.config import settings
from app.core.database import DefaultSessionProvider, build_engine
from app.core.firebase import VerifiedIdentity
from app.main import create_app
from tests.api.admin_analytics.support import PRICE_IDS
from tests.api.admin_subscriptions.conftest import _migrate
from tests.api.admin_subscriptions.support import KEY, LOCAL_HOSTS, TEST_DATABASE_URL
from tests.fakes_admin_analytics import FakeLister, FakePrices


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    assert TEST_DATABASE_URL is not None
    target = make_url(TEST_DATABASE_URL)
    assert (target.database or "").endswith("_test"), (
        "refusing to rebuild a database whose name does not end in _test"
    )
    assert target.host in LOCAL_HOSTS, "refusing to rebuild a non-local database"
    _migrate(TEST_DATABASE_URL, "downgrade", "base")
    _migrate(TEST_DATABASE_URL, "upgrade", "head")
    yield TEST_DATABASE_URL


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    built = build_engine(database_url)
    async with built.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE users, organizations, audit_logs, app_settings, "
                "feature_flags CASCADE"
            )
        )
    yield built
    await built.dispose()


@pytest.fixture(autouse=True)
def price_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in PRICE_IDS.items():
        monkeypatch.setattr(settings, name, value)


@pytest.fixture
def prices() -> FakePrices:
    return FakePrices({"price_pro_m": 2900, "price_pro_y": 24000, "price_ent_m": 9900})


@pytest.fixture
def lister() -> FakeLister:
    return FakeLister([])


@pytest.fixture
async def client(
    engine: AsyncEngine, prices: FakePrices, lister: FakeLister
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    app.dependency_overrides[get_session_provider] = lambda: provider
    app.dependency_overrides[stripe_prices] = lambda: prices
    app.dependency_overrides[stripe_lister] = lambda: lister

    async def identity(
        x_test_uid: Annotated[str | None, Header()] = None,
    ) -> VerifiedIdentity:
        if x_test_uid is None:
            raise HTTPException(401, "Invalid authentication")
        return VerifiedIdentity(
            x_test_uid, f"{x_test_uid}@example.com", True, int(time.time())
        )

    app.dependency_overrides[get_session_identity] = identity
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        http.app = app  # type: ignore[attr-defined]
        yield http
