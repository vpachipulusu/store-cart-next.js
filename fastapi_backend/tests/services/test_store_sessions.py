import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.store_crypto import StoreSecretCodec, generate_key
from app.models.platform.store import Store
from app.services import store_secrets, store_sessions
from app.services.store_sessions import (
    StoreDatabaseNotConfigured,
    StoreDatabaseUnavailable,
    StoreNotFound,
    open_store_session,
)

DSN = "postgresql://user:hunter2@ep-x-pooler.neon.tech/store?sslmode=require"


class FakeResult:
    def __init__(self, store: Store | None) -> None:
        self._store = store

    def scalar_one_or_none(self) -> Store | None:
        return self._store


class FakePlatformSession:
    def __init__(self, stores: dict[str, Store]) -> None:
        self._stores = stores

    async def execute(self, statement: Any) -> FakeResult:
        wanted = statement.compile().params["id_1"]
        return FakeResult(self._stores.get(wanted))


class FakeProvider:
    def __init__(self, *stores: Store) -> None:
        self._stores = {store.id: store for store in stores}

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        yield FakePlatformSession(self._stores)


@pytest.fixture
def codec(monkeypatch: pytest.MonkeyPatch) -> StoreSecretCodec:
    built = StoreSecretCodec(generate_key())
    monkeypatch.setattr(store_secrets, "get_codec", lambda: built)
    return built


@pytest.fixture
def built_engines(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    engines: list[Any] = []
    real = store_sessions.build_engine

    def spy(url: str, extra: Any = None) -> Any:
        built = real(url, extra)
        engines.append((url, extra, built))
        return built

    monkeypatch.setattr(store_sessions, "build_engine", spy)
    return engines


def make_store(codec: StoreSecretCodec, store_id: str, dsn: str | None) -> Store:
    store = Store(id=store_id, name="n", slug=store_id)
    if dsn is not None:
        store_secrets.set_connection_string(store, dsn, codec)
    return store


async def test_session_targets_only_the_requested_store(codec, built_engines):
    other = "postgresql://user:other@ep-y-pooler.neon.tech/other"
    provider = FakeProvider(make_store(codec, "a", DSN), make_store(codec, "b", other))

    async with open_store_session("a", provider) as session:
        assert isinstance(session, AsyncSession)
        assert session.bind.url.host == "ep-x-pooler.neon.tech"
        assert session.bind.url.database == "store"

    assert len(built_engines) == 1


async def test_engine_is_null_pool_pooled_safe_and_disposed(codec, built_engines):
    provider = FakeProvider(make_store(codec, "a", DSN))

    async with open_store_session("a", provider):
        pass

    _, extra, engine = built_engines[0]
    assert isinstance(engine.pool, NullPool)
    # The PgBouncer-safe connect args come from build_engine itself (KAN-160).
    assert extra is None


async def test_each_call_builds_its_own_engine(codec, built_engines):
    provider = FakeProvider(make_store(codec, "a", DSN))

    async with open_store_session("a", provider):
        pass
    async with open_store_session("a", provider):
        pass

    assert built_engines[0][2] is not built_engines[1][2]


async def test_unknown_store_is_typed_error(codec):
    with pytest.raises(StoreNotFound) as caught:
        async with open_store_session("nope", FakeProvider()):
            pass
    assert caught.value.store_id == "nope"


async def test_store_without_connection_string_is_not_configured(codec):
    provider = FakeProvider(make_store(codec, "a", None))
    with pytest.raises(StoreDatabaseNotConfigured):
        async with open_store_session("a", provider):
            pass


async def test_undecryptable_value_fails_without_leaking(codec, monkeypatch, caplog):
    store = make_store(codec, "a", DSN)
    monkeypatch.setattr(
        store_secrets, "get_codec", lambda: StoreSecretCodec(generate_key())
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(StoreDatabaseUnavailable) as c:
        async with open_store_session("a", FakeProvider(store)):
            pass
    assert "hunter2" not in caplog.text + str(c.value) + repr(c.value)
    assert (store.connection_string_encrypted or "") not in str(c.value)
    assert c.value.__cause__ is None


async def test_malformed_url_fails_without_leaking(codec, caplog):
    store = make_store(codec, "a", "not a url hunter2")
    with caplog.at_level(logging.DEBUG), pytest.raises(StoreDatabaseUnavailable) as c:
        async with open_store_session("a", FakeProvider(store)):
            pass
    assert "hunter2" not in caplog.text + str(c.value)
    assert c.value.__cause__ is None
