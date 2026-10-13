from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session_provider
from app.main import app
from tests.fakes import FakeSession, FakeSessionProvider, failing_session


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
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert provider.fake_session.statements == ["SELECT 1"]
    assert (provider.opened, provider.closed) == (1, 1)


@pytest.mark.usefixtures("override_provider")
async def test_ready_is_503_when_the_database_is_down(client: AsyncClient) -> None:
    provider = FakeSessionProvider(failing_session())
    app.dependency_overrides[get_session_provider] = lambda: provider

    async with client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert provider.closed == 1


def test_openapi_identifies_storecart() -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "StoreCart API"
    assert schema["paths"]["/health"]["get"]["operationId"] == "health-health_check"
