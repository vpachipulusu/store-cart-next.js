from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.base import Base
from app.core.database import DefaultSessionProvider, async_session_maker, engine


def test_engine_keeps_null_pool_for_serverless() -> None:
    assert isinstance(engine.pool, NullPool)


def test_default_session_provider_is_the_platform_provider() -> None:
    from app.api.deps import get_session_provider

    assert isinstance(get_session_provider(), DefaultSessionProvider)


def test_base_is_a_declarative_base() -> None:
    assert issubclass(Base, DeclarativeBase)


def test_session_maker_does_not_expire_on_commit_by_default() -> None:
    assert async_session_maker.kw["expire_on_commit"] is False


async def test_default_provider_yields_an_async_session() -> None:
    provider = DefaultSessionProvider(async_session_maker)

    async with provider.session() as session:
        assert isinstance(session, AsyncSession)


async def test_default_provider_uses_the_maker_it_was_given() -> None:
    maker = async_sessionmaker(engine)
    provider = DefaultSessionProvider(maker)

    async with provider.session() as session:
        assert session.bind is engine
