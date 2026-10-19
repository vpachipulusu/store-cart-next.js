"""/health/ready reports a platform database behind the code's migrations (KAN-253)."""

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import ProgrammingError

from app.api.deps import get_health_service
from app.core.platform_schema import platform_heads
from app.main import app
from app.services.health import HealthService

KEY_HEADER = {"X-Internal-Key": "test-only-internal-service-key-not-for-deployment"}


class FakeHealthRepository:
    def __init__(
        self, revision: str | None, revision_error: Exception | None = None
    ) -> None:
        self._revision = revision
        self._revision_error = revision_error

    async def ping(self) -> bool:
        return True

    async def applied_revision(self) -> str | None:
        if self._revision_error is not None:
            raise self._revision_error
        return self._revision


@pytest.fixture
def client() -> Iterator[AsyncClient]:
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def _serve(repository: FakeHealthRepository) -> None:
    service = HealthService(repository)  # type: ignore[arg-type]
    app.dependency_overrides[get_health_service] = lambda: service


async def test_ready_is_ok_when_the_database_is_at_the_code_head(
    client: AsyncClient,
) -> None:
    (head,) = platform_heads()
    _serve(FakeHealthRepository(head))

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["migrations"] == {"pending": False, "current": head, "head": head}


async def test_ready_is_503_when_the_database_is_behind_the_code_head(
    client: AsyncClient,
) -> None:
    _serve(FakeHealthRepository("0009"))

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "migrations_pending"
    assert body["migrations"] == {
        "pending": True,
        "current": "0009",
        "head": platform_heads()[0],
    }


async def test_ready_is_503_when_the_revision_cannot_be_read(
    client: AsyncClient,
) -> None:
    # No alembic_version table: the database was never migrated.
    missing = ProgrammingError("SELECT version_num", {}, Exception("undefined table"))
    _serve(FakeHealthRepository(None, revision_error=missing))

    async with client:
        response = await client.get("/health/ready", headers=KEY_HEADER)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "migrations_pending"
    assert body["migrations"]["pending"] is True
    assert body["migrations"]["current"] is None
