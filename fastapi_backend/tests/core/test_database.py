from typing import Any

import pytest
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core import database
from app.core.base import Base
from app.core.database import (
    DefaultSessionProvider,
    async_session_maker,
    build_engine,
    engine,
)
from app.core.db_url import to_async_target


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


def test_build_engine_passes_sslmode_to_asyncpg_and_keeps_null_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    real = database.create_async_engine

    def spy(url: Any, **kwargs: Any) -> AsyncEngine:
        captured.update(kwargs)
        return real(url, **kwargs)

    monkeypatch.setattr(database, "create_async_engine", spy)

    built = build_engine("postgresql://u:s3cret-pw@ep-x.neon.tech/app?sslmode=require")

    assert captured["connect_args"] == {"ssl": "require"}
    assert captured["poolclass"] is NullPool
    assert isinstance(built.pool, NullPool)
    assert built.url.drivername == "postgresql+asyncpg"
    assert dict(built.url.query) == {}


def test_build_engine_without_tls_parameter_sets_no_ssl_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    real = database.create_async_engine

    def spy(url: Any, **kwargs: Any) -> AsyncEngine:
        captured.update(kwargs)
        return real(url, **kwargs)

    monkeypatch.setattr(database, "create_async_engine", spy)

    build_engine("postgresql://u:pw@localhost:5432/app")

    assert captured["connect_args"] == {}


def test_engine_and_target_reprs_never_contain_the_password() -> None:
    raw = "postgresql://u:s3cret-pw@ep-x.neon.tech/app?sslmode=require"
    built = build_engine(raw)

    assert "s3cret-pw" not in repr(built)
    assert "s3cret-pw" not in str(built.url)
    assert "s3cret-pw" not in repr(to_async_target(raw))
