from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.deps import get_session_provider
from app.core.config import settings
from app.core.platform_schema import PLATFORM_HEAD
from app.main import app, create_app
from tests.fakes import FakeResult, FakeSession, FakeSessionProvider, failing_session


class MigratedSession(FakeSession):
    """Answers SELECT 1 and reports the platform database at this build's head."""

    async def execute(self, statement: Any) -> FakeResult:
        result = await super().execute(statement)
        if "alembic_version" in str(statement):
            return FakeResult(PLATFORM_HEAD)
        return result


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
    provider = FakeSessionProvider(MigratedSession())
    app.dependency_overrides[get_session_provider] = lambda: provider

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provisioning"] == {"ready": True, "missing": []}
    assert body["migrations"] == {
        "pending": False,
        "current": PLATFORM_HEAD,
        "head": PLATFORM_HEAD,
    }
    assert provider.fake_session.statements == [
        "SELECT 1",
        "SELECT version_num FROM alembic_version",
    ]
    assert (provider.opened, provider.closed) == (1, 1)


@pytest.mark.usefixtures("override_provider")
async def test_ready_is_503_when_the_database_is_down(client: AsyncClient) -> None:
    provider = FakeSessionProvider(failing_session())
    app.dependency_overrides[get_session_provider] = lambda: provider

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
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
    assert response.json()["status"] == "unavailable"


def test_openapi_identifies_storecart() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "StoreCart API"
    assert schema["paths"]["/health"]["get"]["operationId"] == "health-health_check"


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}])
async def test_ready_rejects_missing_or_wrong_service_key(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    # The key dependency answers 401 before any database dependency is built.
    async with client:
        response = await client.get("/health/ready", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"success": False, "error": "Unauthorized"}


@pytest.mark.usefixtures("override_provider")
async def test_ready_accepts_the_next_rotation_key(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    next_key = "next-internal-key-that-is-at-least-32-chars"
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_KEY_NEXT", SecretStr(next_key))
    provider = FakeSessionProvider(MigratedSession())
    app.dependency_overrides[get_session_provider] = lambda: provider

    async with client:
        response = await client.get(
            "/health/ready", headers={"X-Internal-Key": next_key}
        )

    assert response.status_code == 200


async def test_ready_is_503_when_no_service_key_is_configured(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_KEY", None)
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_KEY_NEXT", None)

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 503


async def test_liveness_stays_open_without_a_key(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/health")

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
@pytest.mark.parametrize(
    ("environment", "vercel_env"),
    [("local", None), ("production", "preview"), ("production", "development")],
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
    [
        ("production", None),
        ("staging", None),
        ("local", "production"),
        ("local", "unknown"),
    ],
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


async def test_custom_openapi_url_is_ignored_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "VERCEL_ENV", None)
    monkeypatch.setattr(settings, "OPENAPI_URL", "/custom-schema.json")
    prod_app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=prod_app), base_url="http://test"
    ) as http:
        response = await http.get("/custom-schema.json")

    assert response.status_code == 404


@pytest.mark.usefixtures("override_provider")
async def test_ready_names_missing_provisioning_settings_without_values(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeSessionProvider(MigratedSession())
    app.dependency_overrides[get_session_provider] = lambda: provider
    unconfigured = settings.model_copy(
        update={
            "ENVIRONMENT": "production",
            "VERCEL_ENV": None,
            "QSTASH_TOKEN": None,
            "STORE_DB_PROVIDER": "local",
        }
    )
    monkeypatch.setattr("app.api.v1.health.settings", unconfigured)

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 200
    provisioning = response.json()["provisioning"]
    assert provisioning["ready"] is False
    assert "QSTASH_TOKEN" in provisioning["missing"]
    assert "STORE_DB_PROVIDER" in provisioning["missing"]
