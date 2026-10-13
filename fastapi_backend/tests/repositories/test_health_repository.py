import pytest

from app.repositories.health import HealthRepository
from tests.fakes import FakeSession, FakeSessionProvider, as_provider


async def test_repository_uses_the_session_from_the_injected_provider() -> None:
    fake = FakeSession(value=1)
    provider = FakeSessionProvider(fake)

    async with as_provider(provider).session() as session:
        repository = HealthRepository(session)
        assert await repository.ping() is True

    assert fake.statements == ["SELECT 1"]
    assert (provider.opened, provider.closed) == (1, 1)


async def test_repository_ping_is_false_when_database_answers_unexpectedly() -> None:
    provider = FakeSessionProvider(FakeSession(value=0))

    async with provider.session() as session:
        assert await HealthRepository(session).ping() is False


async def test_session_is_closed_when_the_repository_raises() -> None:
    boom = RuntimeError("boom")
    provider = FakeSessionProvider(FakeSession(error=boom))

    with pytest.raises(RuntimeError):
        async with provider.session() as session:
            await HealthRepository(session).ping()

    assert provider.closed == 1
