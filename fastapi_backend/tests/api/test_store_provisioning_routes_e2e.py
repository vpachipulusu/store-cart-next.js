# ruff: noqa: F401, F811 - fixtures are imported from the organisations e2e module
"""Store creation and the QStash callbacks on a real Postgres (KAN-56).

Same harness as ``test_organizations_e2e.py`` (real migrations, only Firebase and QStash
replaced); runs only when ``TEST_DATABASE_URL`` is set. Covers the create_store contract
(commit before enqueue, FAILED view, no 500 after commit), the plan quota and the signed
``/step`` and ``/failed`` routes.
"""

import base64
import json
from typing import Any

import pytest
from httpx import AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.deps import SessionDep
from app.api.v1 import organizations as organizations_api
from app.api.v1.internal_provisioning import get_step_runner
from app.api.v1.organizations import JobProvisioningStarter, get_organizations_service
from app.core.config import settings
from app.core.database import DefaultSessionProvider
from app.repositories.organizations import OrganizationsRepository
from app.services import store_provisioning_job
from app.services.organizations import OrganizationsService
from app.services.store_provisioning_job import (
    FAILED_PATH,
    STEP_PATH,
    EnqueueFailed,
    NoopEnqueuer,
    Step,
    StepRunner,
)
from tests.api.test_organizations_e2e import (
    TEST_DATABASE_URL,
    as_user,
    client,
    database_url,
    engine,
    error_of,
    post_store,
    scalar,
    seed_org,
)
from tests.qstash_tokens import make_token

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

BASE = "https://api.example.test"
KEY = "current-signing-key-for-tests"


class SeenEnqueuer:
    """Records the first step and what another connection sees at that moment."""

    def __init__(self, engine: AsyncEngine, error: Exception | None = None) -> None:
        self.engine = engine
        self.error = error
        self.seen: list[tuple[str, Step, str | None]] = []

    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        async with self.engine.connect() as other:
            status = (
                await other.execute(
                    text("SELECT status FROM stores WHERE id = :i"), {"i": store_id}
                )
            ).scalar_one_or_none()
        self.seen.append((store_id, step, status))
        if self.error:
            raise self.error


def use_enqueuer(monkeypatch: pytest.MonkeyPatch, enqueuer: object) -> None:
    monkeypatch.setattr(organizations_api, "get_step_enqueuer", lambda _s: enqueuer)


def app_of(client: AsyncClient) -> Any:
    return client._transport.app  # type: ignore[attr-defined]


async def an_owner_org(engine: AsyncEngine, tier: str = "pro") -> str:
    org_id, _ = await seed_org(engine, "acme", {"olga": "OWNER"}, tier=tier)
    return org_id


async def test_the_store_is_committed_before_the_first_step_is_enqueued(
    client: AsyncClient, engine: AsyncEngine, monkeypatch
):
    enqueuer = SeenEnqueuer(engine)
    use_enqueuer(monkeypatch, enqueuer)
    org_id = await an_owner_org(engine)

    response = await post_store(client, "olga", org_id, "shop-one")

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "PROVISIONING"
    store_id = response.json()["data"]["id"]
    assert enqueuer.seen == [(store_id, Step.CREATE_DATABASE, "PROVISIONING")]


@pytest.mark.parametrize("error", [EnqueueFailed(), UnicodeError("odd")])
async def test_a_failed_enqueue_returns_the_store_as_failed(
    client: AsyncClient, engine: AsyncEngine, monkeypatch, error
):
    use_enqueuer(monkeypatch, SeenEnqueuer(engine, error))
    org_id = await an_owner_org(engine)

    response = await post_store(client, "olga", org_id, "shop-one")

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "FAILED"
    assert (
        await scalar(engine, "SELECT status FROM stores WHERE slug = 'shop-one'")
        == "FAILED"
    )


async def test_a_crash_while_marking_failed_never_becomes_a_500(
    client: AsyncClient, engine: AsyncEngine, monkeypatch
):
    use_enqueuer(monkeypatch, SeenEnqueuer(engine, EnqueueFailed()))

    async def broken(provider: Any, store_id: str) -> bool:
        raise RuntimeError("database went away")

    monkeypatch.setattr(store_provisioning_job, "mark_failed", broken)
    org_id = await an_owner_org(engine)

    response = await post_store(client, "olga", org_id, "shop-one")

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "FAILED"
    assert (
        await scalar(engine, "SELECT status FROM stores WHERE slug = 'shop-one'")
        == "PROVISIONING"
    )


async def test_a_crashing_starter_does_not_hide_the_committed_store(
    client: AsyncClient, engine: AsyncEngine
):
    class Crashing:
        async def start(self, store_id: str) -> bool:
            raise RuntimeError("boom")

    def build(session: SessionDep) -> OrganizationsService:
        return OrganizationsService(
            OrganizationsRepository(session), session, Crashing()
        )

    app_of(client).dependency_overrides[get_organizations_service] = build
    org_id = await an_owner_org(engine)

    response = await post_store(client, "olga", org_id, "shop-one")

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "FAILED"
    assert await scalar(engine, "SELECT count(*) FROM stores") == 1


async def test_the_default_wiring_uses_the_noop_enqueuer_in_test(
    client: AsyncClient, engine: AsyncEngine
):
    org_id = await an_owner_org(engine)
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )

    service = get_organizations_service(None, provider)  # type: ignore[arg-type]
    starter = service._provisioning

    assert isinstance(starter, JobProvisioningStarter)
    assert isinstance(starter.enqueuer, NoopEnqueuer)
    response = await post_store(client, "olga", org_id, "shop-one")
    assert response.status_code == 201
    assert response.json()["data"]["status"] == "PROVISIONING"


async def test_failed_stores_do_not_count_against_the_plan_limit(
    client: AsyncClient, engine: AsyncEngine
):
    org_id, _ = await seed_org(
        engine, "acme", {"olga": "OWNER"}, stores={"broken": "FAILED"}, tier="free"
    )

    response = await post_store(client, "olga", org_id, "shop-two")

    assert response.status_code == 201
    blocked = await post_store(client, "olga", org_id, "shop-three")
    assert blocked.status_code == 409
    assert (
        error_of(blocked)
        == "The Free plan allows 1 store. Upgrade your plan to add more."
    )


# --- signed callbacks against the real database --------------------------------


@pytest.fixture
def signed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROVISIONING_BASE_URL", BASE)
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", SecretStr(KEY))


async def post_signed(client: AsyncClient, path: str, body: bytes) -> Response:
    token = make_token(body, f"{BASE}{path}", KEY)
    return await client.post(path, content=body, headers={"Upstash-Signature": token})


def callback(store_id: str) -> bytes:
    source = json.dumps({"store_id": store_id, "step": "run_migrations"}).encode()
    return json.dumps({"sourceBody": base64.b64encode(source).decode()}).encode()


async def test_the_failure_callback_flips_provisioning_and_leaves_active_alone(
    client: AsyncClient, engine: AsyncEngine, signed
):
    _, ids = await seed_org(
        engine,
        "acme",
        {"olga": "OWNER"},
        stores={"building": "PROVISIONING", "live": "ACTIVE"},
    )

    first = await post_signed(client, FAILED_PATH, callback(ids["building"]))
    second = await post_signed(client, FAILED_PATH, callback(ids["live"]))

    assert (first.status_code, second.status_code) == (200, 200)
    statuses = {
        slug: await scalar(engine, "SELECT status FROM stores WHERE id = :i", i=i)
        for slug, i in ids.items()
    }
    assert statuses == {"building": "FAILED", "live": "ACTIVE"}


async def test_an_unexpected_step_error_answers_500_and_leaves_the_store(
    client: AsyncClient, engine: AsyncEngine, signed
):
    _, ids = await seed_org(
        engine, "acme", {"olga": "OWNER"}, stores={"building": "PROVISIONING"}
    )
    provider = DefaultSessionProvider(
        async_sessionmaker(engine, expire_on_commit=False)
    )

    class Boom:
        async def create_database(self, store_id: str) -> str:
            raise RuntimeError("postgresql://owner:hunter2@ep-secret/db exploded")

    class Quiet:
        async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
            raise AssertionError("must not advance")

    runner = StepRunner(
        provider=provider,
        provisioner=lambda: Boom(),  # type: ignore[arg-type,return-value]
        enqueuer=Quiet(),
    )
    app_of(client).dependency_overrides[get_step_runner] = lambda: runner
    body = json.dumps({"store_id": ids["building"], "step": "create_database"}).encode()

    response = await post_signed(client, STEP_PATH, body)

    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert (
        await scalar(
            engine, "SELECT status FROM stores WHERE id = :i", i=ids["building"]
        )
        == "PROVISIONING"
    )
