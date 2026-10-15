import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.store_provisioning import (
    InvalidStoreId,
    LocalDatabaseProvisioner,
    NeonDatabaseProvisioner,
    ProvisionerNotConfigured,
    ProvisioningFailed,
    database_name_for,
    get_database_provisioner,
)

STORE_ID = "clx1abcd2efgh3ijkl4mnop5"
API_KEY = "neon-secret-api-key-123"
NEON_URI = "postgresql://owner:hunter2@ep-x-pooler.neon.tech/store_x?sslmode=require"
BASE = "https://neon.test/api/v2"
DB_PATH = "/api/v2/projects/proj-1/branches/br-1/databases"
URI_PATH = "/api/v2/projects/proj-1/connection_uri"


class FakeNeon:
    """In-memory Neon API behind httpx.MockTransport."""

    def __init__(self, existing: tuple[str, ...] = (), post_status: int = 201) -> None:
        self.databases = list(existing)
        self.post_status = post_status
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == DB_PATH:
            return httpx.Response(
                200, json={"databases": [{"name": name} for name in self.databases]}
            )
        if request.method == "POST" and path == DB_PATH:
            if self.post_status in (200, 201):
                self.databases.append(json.loads(request.content)["database"]["name"])
            return httpx.Response(self.post_status, json={})
        if request.method == "DELETE" and path.startswith(f"{DB_PATH}/"):
            name = path.rsplit("/", 1)[1]
            if name not in self.databases:
                return httpx.Response(404, json={})
            self.databases.remove(name)
            return httpx.Response(200, json={})
        if request.method == "GET" and path == URI_PATH:
            return httpx.Response(200, json={"uri": NEON_URI})
        return httpx.Response(500, json={})

    def provisioner(self) -> NeonDatabaseProvisioner:
        return neon_with(self.handle)


def neon_with(handler: httpx.MockTransport | object) -> NeonDatabaseProvisioner:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return NeonDatabaseProvisioner(
        API_KEY,
        "proj-1",
        "br-1",
        "owner",
        base_url=BASE,
        client=httpx.AsyncClient(transport=transport),
    )


def test_database_name_is_prefixed_store_id() -> None:
    assert database_name_for(STORE_ID) == f"store_{STORE_ID}"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "x",
        'a"; DROP DATABASE x; --',
        "UPPERCASE12345678",
        "has-dash-12345678",
        "a" * 41,
    ],
)
def test_database_name_rejects_unsafe_ids(bad: str) -> None:
    with pytest.raises(InvalidStoreId):
        database_name_for(bad)


async def test_neon_creates_database_and_returns_pooled_uri() -> None:
    fake = FakeNeon()

    uri = await fake.provisioner().create_database(STORE_ID)

    assert uri == NEON_URI
    assert fake.databases == [f"store_{STORE_ID}"]
    post = next(r for r in fake.requests if r.method == "POST")
    assert json.loads(post.content) == {
        "database": {"name": f"store_{STORE_ID}", "owner_name": "owner"}
    }
    assert post.headers["Authorization"] == f"Bearer {API_KEY}"
    uri_request = fake.requests[-1]
    assert uri_request.url.params["pooled"] == "true"
    assert uri_request.url.params["database_name"] == f"store_{STORE_ID}"
    assert uri_request.url.params["role_name"] == "owner"


async def test_neon_create_is_idempotent() -> None:
    fake = FakeNeon(existing=(f"store_{STORE_ID}",))

    uri = await fake.provisioner().create_database(STORE_ID)

    assert uri == NEON_URI
    assert not [r for r in fake.requests if r.method == "POST"]


async def test_neon_conflict_on_create_counts_as_created() -> None:
    fake = FakeNeon(post_status=409)

    assert await fake.provisioner().create_database(STORE_ID) == NEON_URI


async def test_neon_exists_and_delete() -> None:
    fake = FakeNeon(existing=(f"store_{STORE_ID}",))
    provisioner = fake.provisioner()

    assert await provisioner.database_exists(STORE_ID) is True
    await provisioner.delete_database(STORE_ID)
    assert await provisioner.database_exists(STORE_ID) is False
    await provisioner.delete_database(STORE_ID)  # already gone: no error


async def test_neon_rejects_invalid_store_id_before_any_request() -> None:
    fake = FakeNeon()

    with pytest.raises(InvalidStoreId):
        await fake.provisioner().create_database("x'; drop")

    assert fake.requests == []


async def test_neon_failure_carries_no_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": f"bad key {API_KEY} {NEON_URI}"})

    with caplog.at_level(logging.DEBUG), pytest.raises(ProvisioningFailed) as caught:
        await neon_with(reject).create_database(STORE_ID)

    shown = f"{caught.value!s} {caplog.text}"
    assert STORE_ID in str(caught.value)
    assert API_KEY not in shown
    assert "hunter2" not in shown


async def test_neon_transport_error_is_wrapped() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} with {API_KEY}")

    with pytest.raises(ProvisioningFailed) as caught:
        await neon_with(boom).database_exists(STORE_ID)

    assert API_KEY not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("body", [{"nope": 1}, {"uri": ""}, {"uri": 5}])
async def test_neon_bad_connection_uri_body_fails(body: dict[str, object]) -> None:
    fake = FakeNeon(existing=(f"store_{STORE_ID}",))

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == URI_PATH:
            return httpx.Response(200, json=body)
        return fake.handle(request)

    with pytest.raises(ProvisioningFailed):
        await neon_with(handle).create_database(STORE_ID)


def settings(**overrides: object) -> Settings:
    return Settings(  # type: ignore[call-arg]
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", **overrides
    )


def test_factory_defaults_to_local() -> None:
    assert isinstance(get_database_provisioner(settings()), LocalDatabaseProvisioner)


def test_factory_builds_neon_when_configured() -> None:
    configured = settings(
        STORE_DB_PROVIDER="Neon",
        NEON_API_KEY=SecretStr(API_KEY),
        NEON_PROJECT_ID="proj-1",
        NEON_BRANCH_ID="br-1",
        NEON_ROLE_NAME="owner",
    )

    assert isinstance(get_database_provisioner(configured), NeonDatabaseProvisioner)


def test_factory_names_missing_neon_variables_without_values() -> None:
    incomplete = settings(STORE_DB_PROVIDER="neon", NEON_API_KEY=SecretStr(API_KEY))

    with pytest.raises(ProvisionerNotConfigured) as caught:
        get_database_provisioner(incomplete)

    assert caught.value.missing == (
        "NEON_PROJECT_ID",
        "NEON_BRANCH_ID",
        "NEON_ROLE_NAME",
    )
    assert API_KEY not in str(caught.value)


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ProvisionerNotConfigured):
        get_database_provisioner(settings(STORE_DB_PROVIDER="mongo"))
