import asyncio
import logging

import asyncpg
import pytest
from sqlalchemy.exc import (
    DBAPIError,
    MultipleResultsFound,
    NoResultFound,
    OperationalError,
    ProgrammingError,
)

from app.core.db_url import CONNECT_TIMEOUT_SECONDS
from app.core.platform_schema import PLATFORM_HEAD, PLATFORM_REVISIONS
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


class DriverError(Exception):
    """Stands in for an asyncpg error: carries the Postgres SQLSTATE."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__("driver message that may name the host")
        self.sqlstate = sqlstate


class FakeRepository:
    """Answers the ping and the revision read separately (KAN-253)."""

    def __init__(
        self,
        revision: str | None = PLATFORM_HEAD,
        revision_error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self._revision = revision
        self._revision_error = revision_error
        self._delay = delay

    async def ping(self) -> bool:
        await asyncio.sleep(self._delay)
        return True

    async def applied_revision(self) -> str | None:
        await asyncio.sleep(self._delay)
        if self._revision_error is not None:
            raise self._revision_error
        return self._revision


def _service(repository: FakeRepository) -> HealthService:
    return HealthService(repository)  # type: ignore[arg-type]


def _programming_error(sqlstate: str) -> ProgrammingError:
    return ProgrammingError("SELECT version_num", {}, DriverError(sqlstate))


async def test_readiness_is_ok_at_the_head() -> None:
    result = await _service(FakeRepository(PLATFORM_HEAD)).readiness()

    assert result.state == "ok"
    assert result.schema is not None
    assert result.schema.pending is False


async def test_readiness_is_pending_when_the_database_is_behind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    previous = PLATFORM_REVISIONS[-2]

    with caplog.at_level(logging.ERROR, logger="app.services.health"):
        result = await _service(FakeRepository(previous)).readiness()

    assert result.state == "migrations_pending"
    assert result.schema is not None
    assert result.schema.current == previous
    assert f"current={previous}" in caplog.text
    assert "alembic upgrade head" in caplog.text


@pytest.mark.parametrize(
    "error",
    [_programming_error("42P01"), NoResultFound()],
    ids=["undefined_table", "no_row"],
)
async def test_readiness_is_pending_when_no_revision_is_recorded(
    error: Exception,
) -> None:
    result = await _service(FakeRepository(revision_error=error)).readiness()

    assert result.state == "migrations_pending"
    assert result.schema is not None
    assert result.schema.current is None


@pytest.mark.parametrize(
    "error",
    [
        _programming_error("42501"),  # insufficient_privilege on alembic_version
        MultipleResultsFound(),
        OperationalError("SELECT version_num", {}, Exception("connection lost")),
    ],
    ids=["permission_denied", "several_rows", "connection_lost"],
)
async def test_readiness_is_unavailable_not_pending_on_other_errors(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    # An outage or a privilege problem must not tell operators to run migrations.
    with caplog.at_level(logging.ERROR, logger="app.services.health"):
        result = await _service(FakeRepository(revision_error=error)).readiness()

    assert result.state == "unavailable"
    assert result.schema is None
    assert "alembic upgrade head" not in caplog.text
    assert "may name the host" not in caplog.text


async def test_readiness_is_unavailable_when_the_ping_fails() -> None:
    provider = FakeSessionProvider(failing_session())

    async with provider.session() as session:
        result = await HealthService(HealthRepository(session)).readiness()

    assert result.state == "unavailable"
    assert result.schema is None
    assert provider.fake_session.statements == ["SELECT 1"]


async def test_ping_and_revision_read_share_one_time_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each step alone fits the budget; together they do not.
    monkeypatch.setattr(health, "READINESS_TIMEOUT_SECONDS", 0.3)

    result = await _service(FakeRepository(delay=0.2)).readiness()

    assert result.state == "unavailable"
