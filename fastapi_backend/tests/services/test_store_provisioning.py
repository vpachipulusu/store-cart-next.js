import json
import logging

import httpx
import pytest
from sqlalchemy.engine import make_url

from app.services.store_provisioning import (
    InvalidStoreId,
    NeonDatabaseProvisioner,
    ProvisioningFailed,
    database_name_for,
)
from tests.fakes_provisioning import (
    API_KEY,
    NEON_DIRECT_URI,
    NEON_URI,
    URI_PATH,
    FakeEngine,
    FakeNeon,
    fake_admin_connection,
    neon_with,
)

STORE_ID = "clx1abcd2efgh3ijkl4mnop5"
NAME = f"store_{STORE_ID}"


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


def assert_store_role_uri(uri: str, engine: FakeEngine) -> None:
    """Pooled host and options from Neon, signed in as the store role."""
    url, pooled = make_url(uri), make_url(NEON_URI)
    assert (url.host, url.query) == (pooled.host, pooled.query)
    assert url.username == NAME
    assert url.password == engine.roles[NAME]
    assert "hunter2" not in uri


async def test_neon_creates_database_and_returns_pooled_uri() -> None:
    fake, engine = FakeNeon(), FakeEngine()

    uri = await fake.provisioner(engine).create_database(STORE_ID)

    assert_store_role_uri(uri, engine)
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


async def test_neon_sets_up_the_store_role_over_the_direct_endpoint() -> None:
    fake, engine = FakeNeon(), FakeEngine()

    await fake.provisioner(engine).create_database(STORE_ID)

    assert engine.admin_uris == [NEON_DIRECT_URI.replace("store_x", NAME)]
    direct = next(r for r in fake.requests if r.url.path == URI_PATH)
    assert direct.url.params["pooled"] == "false"
    assert engine.statements[1:] == [
        f"CREATE ROLE {NAME} PASSWORD <redacted>",
        f'GRANT "{NAME}" TO CURRENT_USER',
        f'ALTER DATABASE "{NAME}" OWNER TO "{NAME}"',
        f'REVOKE CONNECT, TEMPORARY ON DATABASE "{NAME}" FROM PUBLIC',
    ]
    assert engine.owners == {NAME: NAME}


async def test_neon_create_is_idempotent_and_rotates_the_password() -> None:
    fake, engine = FakeNeon(existing=(f"store_{STORE_ID}",)), FakeEngine()
    provisioner = fake.provisioner(engine)

    first = await provisioner.create_database(STORE_ID)
    second = await provisioner.create_database(STORE_ID)

    assert not [r for r in fake.requests if r.method == "POST"]
    assert make_url(first).password != make_url(second).password
    assert_store_role_uri(second, engine)
    assert f"ALTER ROLE {NAME} PASSWORD <redacted>" in engine.statements


async def test_neon_conflict_on_create_counts_as_created() -> None:
    fake, engine = FakeNeon(post_status=409), FakeEngine()

    assert_store_role_uri(
        await fake.provisioner(engine).create_database(STORE_ID), engine
    )


async def test_neon_role_sql_failure_carries_no_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = FakeEngine()
    engine.fail.add("role")

    with caplog.at_level(logging.DEBUG), pytest.raises(ProvisioningFailed) as caught:
        await FakeNeon().provisioner(engine).create_database(STORE_ID)

    shown = f"{caught.value!s} {caplog.text}"
    assert "s3cret" not in shown
    assert "hunter2" not in shown
    assert "PASSWORD" not in shown
    assert caught.value.__cause__ is None


async def test_neon_delete_drops_the_store_role_before_the_database() -> None:
    fake, engine = FakeNeon(), FakeEngine()
    provisioner = fake.provisioner(engine)
    await provisioner.create_database(STORE_ID)

    await provisioner.delete_database(STORE_ID)

    assert NAME not in engine.roles
    assert f'REASSIGN OWNED BY "{NAME}" TO CURRENT_USER' in engine.statements
    assert fake.requests[-1].method == "DELETE"
    assert fake.databases == []


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


async def test_neon_locked_branch_maps_to_failure_without_leaking(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeNeon()

    def locked(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(423, json={"message": f"locked {API_KEY} {NEON_URI}"})
        return fake.handle(request)

    with caplog.at_level(logging.DEBUG), pytest.raises(ProvisioningFailed) as caught:
        await neon_with(locked).create_database(STORE_ID)

    shown = f"{caught.value!s} {caplog.text}"
    assert API_KEY not in shown
    assert "hunter2" not in shown
    assert "423" in caplog.text


async def test_neon_quotes_ids_once_in_paths_and_not_in_query() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET" and request.url.path.endswith("/databases"):
            return httpx.Response(200, json={"databases": [{"name": NAME}]})
        return httpx.Response(200, json={"uri": NEON_URI})

    provisioner = NeonDatabaseProvisioner(
        API_KEY,
        "proj/1",
        "br 1",
        "owner",
        base_url="https://neon.test/api/v2",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        admin_connection=fake_admin_connection(FakeEngine()),
    )

    await provisioner.create_database(STORE_ID)

    assert seen[0].url.raw_path.startswith(
        b"/api/v2/projects/proj%2F1/branches/br%201/databases"
    )
    assert seen[1].url.params["branch_id"] == "br 1"
