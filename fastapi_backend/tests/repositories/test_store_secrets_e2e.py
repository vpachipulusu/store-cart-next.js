"""Store connection string persistence against a real Postgres (KAN-53).

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local database whose name
ends in ``_test`` and which is already migrated to head (the other e2e modules do it).
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.ids import new_id
from app.core.store_crypto import StoreSecretCodec, StoreSecretUnavailable, generate_key
from app.models.platform.store import Store
from app.services import store_secrets

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
DSN = "postgresql://user:hunter2@db.example.invalid/store"

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert TEST_DATABASE_URL is not None
    target = make_url(TEST_DATABASE_URL)
    assert (target.database or "").endswith("_test")
    built = create_async_engine(TEST_DATABASE_URL)
    yield built
    await built.dispose()


async def test_encrypted_value_is_persisted_and_round_trips(engine: AsyncEngine):
    org_id, store_id = new_id(), new_id()
    codec = StoreSecretCodec(generate_key())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:i, 'O', :s)"),
            {"i": org_id, "s": f"org-{org_id}"},
        )
    async with sessions() as session:
        store = Store(
            id=store_id, organization_id=org_id, name="S", slug=f"st-{store_id}"
        )
        store_secrets.set_connection_string(store, DSN, codec)
        session.add(store)
        await session.commit()

    async with engine.connect() as connection:
        raw = (
            await connection.execute(
                text("SELECT connection_string_encrypted FROM stores WHERE id = :i"),
                {"i": store_id},
            )
        ).scalar_one()
    assert "hunter2" not in raw

    async with sessions() as session:
        loaded = (
            await session.execute(select(Store).where(Store.id == store_id))
        ).scalar_one()
        assert store_secrets.reveal_connection_string(loaded, codec) == DSN
        with pytest.raises(StoreSecretUnavailable):
            store_secrets.reveal_connection_string(
                loaded, StoreSecretCodec(generate_key())
            )
