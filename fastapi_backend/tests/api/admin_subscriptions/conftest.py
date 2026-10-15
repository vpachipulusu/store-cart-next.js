"""Fixtures for the admin subscriptions e2e tests (KAN-48): real Postgres, fake Firebase and Stripe.

Same contract as ``tests/api/test_admin_users_e2e.py``: runs only when ``TEST_DATABASE_URL``
points at a throwaway local database whose name ends in "_test", and rebuilds its schema
with the real Alembic migrations. Only Firebase (identity from an ``X-Test-Uid`` header)
and Stripe (``FakeStripeAdmin``, never the network) are replaced.
"""

import os
import subprocess
import sys
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
from app.api.v1.admin_subscriptions import stripe_admin
from app.core.database import DefaultSessionProvider, build_engine
from app.core.firebase import VerifiedIdentity
from app.main import create_app
from tests.api.admin_subscriptions.support import (
    BACKEND_ROOT,
    KEY,
    LOCAL_HOSTS,
    TEST_DATABASE_URL,
)
from tests.fakes_admin_subscriptions import FakeStripeAdmin


def _migrate(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL_DIRECT": url},
        check=True,
        capture_output=True,
    )


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
            text("TRUNCATE users, organizations, audit_logs CASCADE")
        )
    yield built
    await built.dispose()


@pytest.fixture
def stripe() -> FakeStripeAdmin:
    return FakeStripeAdmin()


@pytest.fixture
async def client(
    engine: AsyncEngine, stripe: FakeStripeAdmin
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    app.dependency_overrides[get_session_provider] = lambda: provider
    app.dependency_overrides[stripe_admin] = lambda: stripe

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
