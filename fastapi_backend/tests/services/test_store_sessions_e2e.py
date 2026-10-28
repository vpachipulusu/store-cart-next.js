"""Store session factory against a real Postgres (KAN-54).

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local database whose name
ends in ``_test`` and which is already migrated to head. Two extra databases play the
store databases; they are created and dropped by the fixture.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database import DefaultSessionProvider
from app.core.ids import new_id
from app.core.store_crypto import StoreSecretCodec, generate_key
from app.models.platform.store import Store
from app.services import store_secrets
from app.services.store_sessions import (
    StoreDatabaseNotConfigured,
    StoreDatabaseUnavailable,
    open_store_session,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert TEST_DATABASE_URL is not None
    assert (make_url(TEST_DATABASE_URL).database or "").endswith("_test")
    built = create_async_engine(TEST_DATABASE_URL)
    yield built
    await built.dispose()


@pytest.fixture
async def store_databases(engine: AsyncEngine) -> AsyncIterator[tuple[str, str]]:
    # KAN-238: a store may only open store_<its id>; add_store reads the id back.
    names = (f"store_ks{new_id().lower()}", f"store_ks{new_id().lower()}")
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        for name in names:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    yield names
    async with admin.connect() as connection:
        for name in names:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )


def url_for(database: str) -> str:
    assert TEST_DATABASE_URL is not None
    return make_url(TEST_DATABASE_URL).set(database=database).render_as_string(False)


async def add_store(engine: AsyncEngine, dsn: str | None, codec: StoreSecretCodec):
    database = make_url(dsn).database if dsn else None
    org_id = new_id()
    store_id = database.removeprefix("store_") if database else new_id()
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:i, 'O', :s)"),
            {"i": org_id, "s": f"org-{org_id}"},
        )
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        store = Store(
            id=store_id, organization_id=org_id, name="S", slug=f"st-{store_id}"
        )
        if dsn is not None:
            store_secrets.set_connection_string(store, dsn, codec)
        session.add(store)
        await session.commit()
    return store_id


async def test_each_store_session_reaches_only_its_own_database(
    engine, store_databases, monkeypatch
):
    codec = StoreSecretCodec(generate_key())
    monkeypatch.setattr(store_secrets, "get_codec", lambda: codec)
    db_a, db_b = store_databases
    id_a = await add_store(engine, url_for(db_a), codec)
    id_b = await add_store(engine, url_for(db_b), codec)
    provider = DefaultSessionProvider(async_sessionmaker(engine))

    async with open_store_session(id_a, provider) as session:
        assert (
            await session.execute(text("SELECT current_database()"))
        ).scalar_one() == db_a
    async with open_store_session(id_b, provider) as session:
        assert (
            await session.execute(text("SELECT current_database()"))
        ).scalar_one() == db_b


async def test_no_connection_outlives_the_session(engine, store_databases, monkeypatch):
    codec = StoreSecretCodec(generate_key())
    monkeypatch.setattr(store_secrets, "get_codec", lambda: codec)
    db_a, _ = store_databases
    store_id = await add_store(engine, url_for(db_a), codec)
    provider = DefaultSessionProvider(async_sessionmaker(engine))

    async with open_store_session(store_id, provider) as session:
        await session.execute(text("SELECT 1"))
    async with engine.connect() as connection:
        open_connections = (
            await connection.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = :d"),
                {"d": db_a},
            )
        ).scalar_one()

    assert open_connections == 0


async def test_unprovisioned_and_undecryptable_stores_fail_typed(
    engine, store_databases, monkeypatch
):
    codec = StoreSecretCodec(generate_key())
    db_a, _ = store_databases
    empty_id = await add_store(engine, None, codec)
    sealed_id = await add_store(engine, url_for(db_a), codec)
    provider = DefaultSessionProvider(async_sessionmaker(engine))
    monkeypatch.setattr(
        store_secrets, "get_codec", lambda: StoreSecretCodec(generate_key())
    )

    with pytest.raises(StoreDatabaseNotConfigured):
        async with open_store_session(empty_id, provider):
            pass
    with pytest.raises(StoreDatabaseUnavailable) as caught:
        async with open_store_session(sealed_id, provider):
            pass
    assert "postgresql" not in str(caught.value)
