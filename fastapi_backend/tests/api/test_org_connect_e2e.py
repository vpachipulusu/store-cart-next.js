"""End to end: Connect onboarding, the Connect webhook and the checkout guard on a real Postgres (KAN-67, KAN-69).

Same contract as ``test_org_billing_e2e.py``: runs only when ``TEST_DATABASE_URL`` points at a
throwaway local database whose name ends in "_test", and rebuilds its schema with the real
Alembic migrations (so the 0010 migration is exercised, downgrade and upgrade). Only Firebase and
Stripe are replaced; membership checks, repositories, signature checks and SQL are production code.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import FastAPI, Header, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.auth import get_session_identity
from app.api.deps import SessionDep, get_session_provider
from app.api.v1.org_connect import get_stripe_connect_client
from app.api.v1.webhooks_connect import get_connect_webhook_service
from app.core.config import settings
from app.core.database import DefaultSessionProvider, build_engine
from app.core.firebase import VerifiedIdentity
from app.core.ids import new_id
from app.core.stripe_connect import StripeAccountState
from app.core.stripe_signature import compute_signature
from app.main import create_app
from app.repositories.connect_events import ConnectEventRepository
from app.repositories.org_connect import OrgConnectRepository
from app.services.stripe_connect import (
    ChargesNotEnabled,
    ConnectRoute,
    ConnectWebhookService,
    require_org_charges_enabled,
)
from tests.fakes_connect import FakeStripeConnect

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
KEY = "test-only-internal-service-key-not-for-deployment"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
WEBHOOK_SECRET = "whsec_e2e_connect_only_not_real"
RETURN_URL = "https://app.example.com/dashboard/settings"
T0 = 1_800_000_000

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


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
        await connection.execute(text("TRUNCATE users, organizations CASCADE"))
    yield built
    await built.dispose()


@pytest.fixture
def stripe() -> FakeStripeConnect:
    return FakeStripeConnect()


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(
    app: FastAPI,
    engine: AsyncEngine,
    stripe: FakeStripeConnect,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(
        settings, "BILLING_RETURN_URL_ORIGINS", "https://app.example.com"
    )
    monkeypatch.setattr(
        settings, "STRIPE_CONNECT_WEBHOOK_SECRET", SecretStr(WEBHOOK_SECRET)
    )
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    app.dependency_overrides[get_session_provider] = lambda: provider
    app.dependency_overrides[get_stripe_connect_client] = lambda: stripe
    monkeypatch.setattr(
        "app.api.v1.webhooks_connect.get_stripe_connect", lambda: stripe
    )

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
        yield http


async def seed_org(engine: AsyncEngine, members: dict[str, str]) -> str:
    org_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO organizations (id, name, slug) VALUES (:id, 'Acme', :slug)"
            ),
            {"id": org_id, "slug": f"acme-{org_id}"},
        )
        for user, role in members.items():
            user_id = new_id()
            await connection.execute(
                text(
                    "INSERT INTO users (id, firebase_uid, email, email_verified) "
                    "VALUES (:id, :uid, :email, true) ON CONFLICT DO NOTHING"
                ),
                {"id": user_id, "uid": f"fb-{user}", "email": f"{user}@example.com"},
            )
            found = (
                await connection.execute(
                    text("SELECT id FROM users WHERE firebase_uid = :uid"),
                    {"uid": f"fb-{user}"},
                )
            ).scalar_one()
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :org, :user, :role)"
                ),
                {"id": new_id(), "org": org_id, "user": found, "role": role},
            )
    return org_id


async def connect_row(engine: AsyncEngine, org_id: str) -> tuple[Any, ...]:
    async with engine.connect() as connection:
        row = await connection.execute(
            text(
                "SELECT stripe_connect_account_id, connect_charges_enabled, "
                "connect_payouts_enabled, connect_details_submitted "
                "FROM organizations WHERE id = :id"
            ),
            {"id": org_id},
        )
        return tuple(row.one())


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}"}


def account_event(account_id: str) -> dict[str, Any]:
    """An account.updated trigger; the flags come from Stripe, not from the payload."""
    return {
        "id": f"evt_{new_id()}",
        "type": "account.updated",
        "created": T0,
        "livemode": False,
        "data": {"object": {"id": account_id}},
    }


def deauthorized_event(account_id: str) -> dict[str, Any]:
    return {
        "id": f"evt_{new_id()}",
        "type": "account.application.deauthorized",
        "created": T0,
        "livemode": False,
        "account": account_id,
        "data": {"object": {"id": "ca_platform", "object": "application"}},
    }


def stripe_reports(stripe: FakeStripeConnect, *, charges: bool, payouts: bool = False):
    stripe.account_state = StripeAccountState(charges, payouts, True)


async def deliver(
    client: AsyncClient, event: dict[str, Any], secret: str = WEBHOOK_SECRET
):
    body = json.dumps(event).encode()
    stamp = int(time.time())
    return await client.post(
        "/webhooks/stripe-connect",
        content=body,
        headers={
            "Stripe-Signature": f"t={stamp},v1={compute_signature(secret, stamp, body)}"
        },
    )


async def onboard(client: AsyncClient, org_id: str, user: str = "owner"):
    return await client.post(
        f"/v1/organizations/{org_id}/connect/onboarding-link",
        json={"return_url": RETURN_URL, "refresh_url": RETURN_URL},
        headers=as_user(user),
    )


async def test_owner_onboards_then_account_updated_enables_charges(
    client, engine, stripe
):
    org = await seed_org(engine, {"owner": "OWNER"})

    first = await onboard(client, org)
    status_before = await client.get(
        f"/v1/organizations/{org}/connect", headers=as_user("owner")
    )
    stripe_reports(stripe, charges=True, payouts=True)
    delivered = await deliver(client, account_event("acct_new"))
    status_after = await client.get(
        f"/v1/organizations/{org}/connect", headers=as_user("owner")
    )

    assert first.status_code == 200
    assert first.json()["data"]["url"] == "https://connect.stripe.test/setup/abc"
    assert status_before.json()["data"] == {
        "has_account": True,
        "charges_enabled": False,
        "payouts_enabled": False,
        "details_submitted": False,
    }
    assert delivered.status_code == 200
    assert status_after.json()["data"] == {
        "has_account": True,
        "charges_enabled": True,
        "payouts_enabled": True,
        "details_submitted": True,
    }
    assert stripe.names() == ["create_account", "create_account_link", "get_account"]


async def test_continuing_onboarding_does_not_create_a_second_account(
    client, engine, stripe
):
    org = await seed_org(engine, {"owner": "OWNER"})

    results = [await onboard(client, org) for _ in range(2)]

    assert [r.status_code for r in results] == [200, 200]
    assert stripe.names() == [
        "create_account",
        "create_account_link",
        "create_account_link",
    ]
    assert (await connect_row(engine, org))[0] == "acct_new"


async def test_concurrent_first_requests_all_succeed_and_link_one_account(
    client, engine, stripe
):
    org = await seed_org(engine, {"owner": "OWNER"})

    results = await asyncio.gather(*(onboard(client, org) for _ in range(4)))

    assert [r.status_code for r in results] == [200] * 4
    assert (await connect_row(engine, org))[0] == "acct_new"
    # Several requests reached Stripe at once; the losers saw the in-flight conflict and recovered.
    assert stripe.names().count("create_account") > 1


async def test_staff_cannot_onboard_and_other_organisations_are_hidden(
    client, engine, stripe
):
    org = await seed_org(engine, {"owner": "OWNER", "staff": "STAFF"})
    other = await seed_org(engine, {"rival": "OWNER"})

    staff = await onboard(client, org, "staff")
    rival = await onboard(client, org, "rival")
    rival_status = await client.get(
        f"/v1/organizations/{org}/connect", headers=as_user("rival")
    )

    assert (staff.status_code, rival.status_code, rival_status.status_code) == (
        403,
        404,
        404,
    )
    assert stripe.calls == []
    assert (await connect_row(engine, other))[0] is None


async def test_unknown_account_is_acknowledged_without_touching_a_row(
    client, engine, stripe
):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    stripe_reports(stripe, charges=True)

    unknown = await deliver(client, account_event("acct_nobody"))

    assert unknown.status_code == 200
    assert (await connect_row(engine, org))[1] is False


async def test_events_in_any_order_leave_what_stripe_now_reports(
    client, engine, stripe
):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    stripe_reports(stripe, charges=True)
    first = account_event("acct_new")
    second = account_event("acct_new")  # same second, delivered in reversed order

    responses = [await deliver(client, second), await deliver(client, first)]

    assert [r.status_code for r in responses] == [200, 200]
    assert (await connect_row(engine, org))[1] is True


async def test_deauthorization_clears_the_flags(client, engine, stripe):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    stripe_reports(stripe, charges=True, payouts=True)
    await deliver(client, account_event("acct_new"))

    cleared = await deliver(client, deauthorized_event("acct_new"))

    assert cleared.status_code == 200
    assert (await connect_row(engine, org))[1:] == (False, False, False)


async def test_a_read_that_started_earlier_does_not_overwrite_a_newer_one(engine):
    org = await seed_org(engine, {"owner": "OWNER"})
    maker = async_sessionmaker(engine, expire_on_commit=False)
    newer = datetime(2026, 10, 19, 12, 0, 1, tzinfo=UTC)
    older = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
    async with maker() as session:
        repository = OrgConnectRepository(session)
        await repository.link_account(org, "acct_race")
        applied = await repository.apply_account_update(
            "acct_race",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
            event_at=newer,
        )
        stale = await repository.apply_account_update(
            "acct_race",
            charges_enabled=False,
            payouts_enabled=False,
            details_submitted=False,
            event_at=older,
        )
        await session.commit()

    assert (applied, stale) == (True, False)
    assert (await connect_row(engine, org))[1:] == (True, True, True)


async def test_redelivered_event_leaves_the_same_state(client, engine, stripe):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    stripe_reports(stripe, charges=True)
    event = account_event("acct_new")

    responses = await asyncio.gather(*(deliver(client, event) for _ in range(3)))

    assert [r.status_code for r in responses] == [200] * 3
    assert (await connect_row(engine, org))[1:] == (True, False, True)


async def test_bad_signature_changes_nothing(client, engine, stripe):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    stripe_reports(stripe, charges=True)

    response = await deliver(client, account_event("acct_new"), secret="whsec_wrong")

    assert response.status_code == 400
    assert (await connect_row(engine, org))[1] is False
    assert "get_account" not in stripe.names()


async def test_checkout_guard_blocks_until_charges_are_enabled(client, engine, stripe):
    org = await seed_org(engine, {"owner": "OWNER"})
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        with pytest.raises(ChargesNotEnabled):
            await require_org_charges_enabled(OrgConnectRepository(session), org)
    await onboard(client, org)
    stripe_reports(stripe, charges=False)
    await deliver(client, account_event("acct_new"))
    async with maker() as session:
        with pytest.raises(ChargesNotEnabled):
            await require_org_charges_enabled(OrgConnectRepository(session), org)
    stripe_reports(stripe, charges=True)
    await deliver(client, account_event("acct_new"))
    async with maker() as session:
        await require_org_charges_enabled(OrgConnectRepository(session), org)


# KAN-69: routing and at-most-once processing on the real tables


async def connect_event_rows(engine: AsyncEngine) -> list[tuple[Any, ...]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT stripe_event_id, type, stripe_account_id, organization_id, "
                "store_id FROM stripe_connect_events ORDER BY created_at"
            )
        )
        return [tuple(row) for row in rows]


async def seed_store(engine: AsyncEngine, org_id: str) -> str:
    store_id = new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO stores (id, organization_id, name, slug) "
                "VALUES (:id, :org, 'Shop', :slug)"
            ),
            {"id": store_id, "org": org_id, "slug": f"shop-{store_id}"},
        )
    return store_id


class RecordingStoreHandler:
    def __init__(self) -> None:
        self.routes: list[ConnectRoute] = []
        self.fail = False

    async def __call__(self, route: ConnectRoute, obj: Any) -> None:
        await asyncio.sleep(0.05)  # widen the race window between deliveries
        self.routes.append(route)
        if self.fail:
            raise RuntimeError("handler failed")


@pytest.fixture
def store_handler(app: FastAPI, stripe: FakeStripeConnect) -> RecordingStoreHandler:
    """Serve the Connect webhook with production repositories plus one store-scoped handler."""
    handler = RecordingStoreHandler()

    def service(session: SessionDep) -> ConnectWebhookService:
        return ConnectWebhookService(
            OrgConnectRepository(session),
            ConnectEventRepository(session),
            session,
            lambda: stripe,
            livemode=False,
            store_handlers={"checkout.session.completed": handler},
        )

    app.dependency_overrides[get_connect_webhook_service] = service
    return handler


def checkout_event(account_id: str, store_id: str) -> dict[str, Any]:
    return {
        "id": f"evt_{new_id()}",
        "type": "checkout.session.completed",
        "created": T0,
        "livemode": False,
        "account": account_id,
        "data": {"object": {"id": "cs_1", "metadata": {"store_id": store_id}}},
    }


async def test_concurrent_redeliveries_record_the_event_once(client, engine, stripe):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    stripe_reports(stripe, charges=True)
    event = account_event("acct_new")

    responses = await asyncio.gather(*(deliver(client, event) for _ in range(4)))

    assert [r.status_code for r in responses] == [200] * 4
    assert await connect_event_rows(engine) == [
        (event["id"], "account.updated", "acct_new", org, None)
    ]


async def test_unknown_account_records_nothing(client, engine, stripe):
    await seed_org(engine, {"owner": "OWNER"})

    response = await deliver(client, account_event("acct_nobody"))

    assert response.status_code == 200
    assert await connect_event_rows(engine) == []
    assert stripe.calls == []


async def test_store_events_reach_the_right_store_once(
    client, engine, stripe, store_handler
):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    store = await seed_store(engine, org)
    event = checkout_event("acct_new", store)

    responses = await asyncio.gather(*(deliver(client, event) for _ in range(3)))

    assert [r.status_code for r in responses] == [200] * 3
    assert store_handler.routes == [ConnectRoute(org, "acct_new", store)]
    assert await connect_event_rows(engine) == [
        (event["id"], "checkout.session.completed", "acct_new", org, store)
    ]


async def test_a_store_event_naming_another_organisations_store_is_ignored(
    client, engine, stripe, store_handler
):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    rival = await seed_org(engine, {"rival": "OWNER"})
    rival_store = await seed_store(engine, rival)

    response = await deliver(client, checkout_event("acct_new", rival_store))

    assert response.status_code == 200
    assert store_handler.routes == []
    assert await connect_event_rows(engine) == []


async def test_a_failing_store_handler_records_nothing_and_the_retry_applies_once(
    client, engine, stripe, store_handler
):
    org = await seed_org(engine, {"owner": "OWNER"})
    await onboard(client, org)
    store = await seed_store(engine, org)
    event = checkout_event("acct_new", store)
    store_handler.fail = True

    failed = await deliver(client, event)
    rows_after_failure = await connect_event_rows(engine)
    store_handler.fail = False
    retried = await deliver(client, event)
    again = await deliver(client, event)

    assert failed.status_code == 500
    assert rows_after_failure == []
    assert (retried.status_code, again.status_code) == (200, 200)
    assert len(store_handler.routes) == 2  # the failed attempt and the retry
    assert len(await connect_event_rows(engine)) == 1
