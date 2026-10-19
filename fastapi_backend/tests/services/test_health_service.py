import asyncio
import logging

import asyncpg
import pytest
from alembic.util.exc import CommandError
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.db_url import CONNECT_TIMEOUT_SECONDS
from app.repositories.health import HealthRepository
from app.services import health
from app.services.health import HealthService
from tests.fakes import (
    FakeResult,
    FakeSession,
    FakeSessionProvider,
    failing_session,
)


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


class StalledSession(FakeSession):
    """Connects, then never answers the query."""

    async def execute(self, statement: object) -> FakeResult:
        self.statements.append(str(statement))
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_database_not_ready_when_the_ping_stalls_after_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "READINESS_TIMEOUT_SECONDS", 0.01)
    provider = FakeSessionProvider(StalledSession())

    async with provider.session() as session:
        service = HealthService(HealthRepository(session))
        assert await service.is_database_ready() is False


def test_readiness_timeout_is_bounded_by_the_connect_timeout() -> None:
    assert 0 < health.READINESS_TIMEOUT_SECONDS <= CONNECT_TIMEOUT_SECONDS


async def test_schema_is_pending_when_alembic_version_does_not_exist(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # KAN-253: a database that was never migrated has no alembic_version table.
    missing = ProgrammingError("SELECT version_num", {}, Exception("undefined table"))
    provider = FakeSessionProvider(FakeSession(error=missing))

    with caplog.at_level(logging.ERROR, logger="app.services.health"):
        async with provider.session() as session:
            status = await HealthService(HealthRepository(session)).schema_status()

    assert status is not None
    assert status.pending is True
    assert status.current is None
    assert "alembic upgrade head" in caplog.text


async def test_schema_is_unknown_not_pending_when_the_database_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # An outage must not tell operators to run migrations.
    provider = FakeSessionProvider(failing_session())

    with caplog.at_level(logging.ERROR, logger="app.services.health"):
        async with provider.session() as session:
            status = await HealthService(HealthRepository(session)).schema_status()

    assert status is None
    assert "Platform revision check failed: " in caplog.text
    assert "alembic upgrade head" not in caplog.text


async def test_schema_is_pending_when_the_database_is_behind_this_build(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeSessionProvider(FakeSession(value="0009"))

    with caplog.at_level(logging.ERROR, logger="app.services.health"):
        async with provider.session() as session:
            status = await HealthService(HealthRepository(session)).schema_status()

    assert status is not None
    assert status.pending is True
    assert status.current == "0009"
    assert "current=0009" in caplog.text


async def test_schema_is_unknown_when_the_migration_scripts_are_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreadable(current: str | None) -> None:
        raise CommandError("Path doesn't exist")

    monkeypatch.setattr(health, "platform_schema_status", unreadable)
    provider = FakeSessionProvider(FakeSession(value="0010"))

    async with provider.session() as session:
        assert await HealthService(HealthRepository(session)).schema_status() is None
