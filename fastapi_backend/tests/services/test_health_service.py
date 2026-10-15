import asyncpg
import pytest

from app.repositories.health import HealthRepository
from app.services.health import HealthService
from tests.fakes import FakeSession, FakeSessionProvider, failing_session


async def test_database_ready_when_ping_succeeds() -> None:
    provider = FakeSessionProvider(FakeSession(value=1))

    async with provider.session() as session:
        service = HealthService(HealthRepository(session))
        assert await service.is_database_ready() is True


async def test_database_not_ready_when_the_database_errors() -> None:
    provider = FakeSessionProvider(failing_session())

    async with provider.session() as session:
        service = HealthService(HealthRepository(session))
        assert await service.is_database_ready() is False


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(111, "Connection refused"),
        OSError(113, "No route to host"),
        TimeoutError(),
        asyncpg.PostgresConnectionError("connection failure"),
        asyncpg.CannotConnectNowError("the database system is starting up"),
        asyncpg.TooManyConnectionsError("too many connections"),
        asyncpg.InvalidPasswordError("password authentication failed"),
        asyncpg.InterfaceError("connection is closed"),
    ],
    ids=lambda error: type(error).__name__,
)
async def test_database_not_ready_on_connection_failures(error: Exception) -> None:
    provider = FakeSessionProvider(FakeSession(error=error))

    async with provider.session() as session:
        service = HealthService(HealthRepository(session))
        assert await service.is_database_ready() is False


async def test_unrelated_errors_are_not_swallowed() -> None:
    provider = FakeSessionProvider(FakeSession(error=RuntimeError("bug")))

    async with provider.session() as session:
        service = HealthService(HealthRepository(session))
        with pytest.raises(RuntimeError):
            await service.is_database_ready()
