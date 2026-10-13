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
