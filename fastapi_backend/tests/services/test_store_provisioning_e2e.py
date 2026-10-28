"""Local database provisioner against a real Postgres (KAN-55).

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local database whose name
ends in ``_test``. The role needs CREATEDB (the Docker superuser has it). Databases the
tests create are dropped afterwards.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.ids import new_id
from app.services.store_provisioning import (
    LocalDatabaseProvisioner,
    database_name_for,
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
def store_id() -> str:
    return new_id().lower()


@pytest.fixture
async def provisioner(
    engine: AsyncEngine, store_id: str
) -> AsyncIterator[LocalDatabaseProvisioner]:
    provisioner = LocalDatabaseProvisioner(engine)
    yield provisioner
    await provisioner.delete_database(store_id)


async def test_creates_database_reachable_through_returned_string(
    provisioner: LocalDatabaseProvisioner, store_id: str
) -> None:
    connection_string = await provisioner.create_database(store_id)

    assert make_url(connection_string).database == database_name_for(store_id)
    store_engine = create_async_engine(connection_string)
    try:
        async with store_engine.connect() as connection:
            current = await connection.scalar(text("SELECT current_database()"))
    finally:
        await store_engine.dispose()
    assert current == database_name_for(store_id)


async def test_create_is_idempotent(
    provisioner: LocalDatabaseProvisioner, store_id: str
) -> None:
    first = make_url(await provisioner.create_database(store_id))
    second = make_url(await provisioner.create_database(store_id))

    # KAN-238: same database and role, new password on every call.
    assert (first.database, first.username) == (second.database, second.username)
    assert first.password != second.password
    assert await provisioner.database_exists(store_id) is True


async def test_delete_removes_database_and_is_repeatable(
    provisioner: LocalDatabaseProvisioner, store_id: str
) -> None:
    await provisioner.create_database(store_id)

    await provisioner.delete_database(store_id)
    await provisioner.delete_database(store_id)

    assert await provisioner.database_exists(store_id) is False


async def test_exists_is_false_for_unknown_store(
    provisioner: LocalDatabaseProvisioner,
) -> None:
    assert await provisioner.database_exists(new_id().lower()) is False
