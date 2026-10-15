import logging

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError

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


async def test_logs_the_root_cause_type_without_the_driver_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_detail = 'password authentication failed for user "store_owner"'
    cause = asyncpg.InvalidPasswordError(secret_detail)
    wrapped = DBAPIError("SELECT 1", {}, Exception(secret_detail))
    wrapped.__cause__ = cause
    provider = FakeSessionProvider(FakeSession(error=wrapped))

    with caplog.at_level(logging.ERROR, logger="app.services.health"):
        async with provider.session() as session:
            service = HealthService(HealthRepository(session))
            assert await service.is_database_ready() is False

    [record] = caplog.records
    assert record.getMessage() == (
        "Database readiness check failed: InvalidPasswordError"
    )
    assert record.exc_info is None
    assert "store_owner" not in caplog.text
