from collections.abc import Iterator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session_provider
from app.core.config import settings
from app.main import app, create_app
from tests.fakes import FakeSession, FakeSessionProvider, failing_session

KEY_HEADER = {"X-Internal-Key": "test-only-internal-service-key-not-for-deployment"}


@pytest.fixture
def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def override_provider() -> Iterator[None]:
    """Clear dependency overrides after the test (tests install their own)."""
    yield
    app.dependency_overrides.clear()


async def test_health_returns_ok(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.usefixtures("override_provider")
async def test_ready_is_ok_with_an_injected_fake_session_provider(
    client: AsyncClient,
) -> None:
    provider = FakeSessionProvider(FakeSession(value=1))
    app.dependency_overrides[get_session_provider] = lambda: provider

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert provider.fake_session.statements == ["SELECT 1"]
    assert (provider.opened, provider.closed) == (1, 1)


@pytest.mark.usefixtures("override_provider")
async def test_ready_is_503_when_the_database_is_down(client: AsyncClient) -> None:
    provider = FakeSessionProvider(failing_session())
    app.dependency_overrides[get_session_provider] = lambda: provider

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert provider.closed == 1


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(111, "Connection refused"),
        TimeoutError(),
        asyncpg.CannotConnectNowError("the database system is starting up"),
    ],
    ids=lambda error: type(error).__name__,
)
@pytest.mark.usefixtures("override_provider")
async def test_ready_is_503_not_500_when_the_connection_fails(
    error: Exception,
) -> None:
    provider = FakeSessionProvider(FakeSession(error=error))
    app.dependency_overrides[get_session_provider] = lambda: provider
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_openapi_identifies_storecart() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "StoreCart API"
    assert schema["paths"]["/health"]["get"]["operationId"] == "health-health_check"


@pytest.mark.usefixtures("override_provider")
@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}])
async def test_ready_rejects_missing_or_wrong_service_key_without_touching_db(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    provider = FakeSessionProvider(FakeSession(value=1))
    app.dependency_overrides[get_session_provider] = lambda: provider

    async with client:
        response = await client.get("/health/ready", headers=headers)

    assert response.status_code == 401
    assert provider.opened == 0


async def test_liveness_stays_open_without_a_key(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/health")

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
@pytest.mark.parametrize(
    ("environment", "vercel_env"),
    [("local", None), ("production", "preview")],
)
async def test_docs_are_served_outside_production(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    environment: str,
    vercel_env: str | None,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "VERCEL_ENV", vercel_env)
    local_app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=local_app), base_url="http://test"
    ) as http:
        response = await http.get(path)

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
@pytest.mark.parametrize(
    ("environment", "vercel_env"),
    [("production", None), ("staging", None), ("local", "production")],
)
async def test_docs_are_not_served_in_production(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    environment: str,
    vercel_env: str | None,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "VERCEL_ENV", vercel_env)
    prod_app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=prod_app), base_url="http://test"
    ) as http:
        response = await http.get(path)

    assert response.status_code == 404
    # Schema generation (commands.generate_openapi_schema) must keep working.
    assert prod_app.openapi()["info"]["title"] == "StoreCart API"
