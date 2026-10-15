"""Both provisioners must be substitutable behind ``DatabaseProvisioner`` (KAN-55)."""

from collections.abc import Callable

import pytest

from app.services.store_provisioning import (
    DatabaseProvisioner,
    InvalidStoreId,
    LocalDatabaseProvisioner,
)
from tests.fakes_provisioning import FakeEngine, FakeNeon

STORE_ID = "clx1abcd2efgh3ijkl4mnop5"


def make_local() -> DatabaseProvisioner:
    return LocalDatabaseProvisioner(FakeEngine().as_engine())


def make_neon() -> DatabaseProvisioner:
    return FakeNeon().provisioner()


@pytest.fixture(params=[make_local, make_neon], ids=["local", "neon"])
def provisioner(request: pytest.FixtureRequest) -> DatabaseProvisioner:
    factory: Callable[[], DatabaseProvisioner] = request.param
    return factory()


async def test_create_returns_a_connection_string_and_database_exists(
    provisioner: DatabaseProvisioner,
) -> None:
    assert await provisioner.database_exists(STORE_ID) is False

    connection_string = await provisioner.create_database(STORE_ID)

    assert connection_string
    assert await provisioner.database_exists(STORE_ID) is True


async def test_create_twice_returns_the_same_connection_string(
    provisioner: DatabaseProvisioner,
) -> None:
    first = await provisioner.create_database(STORE_ID)
    second = await provisioner.create_database(STORE_ID)

    assert first == second


async def test_delete_twice_leaves_no_database_and_no_error(
    provisioner: DatabaseProvisioner,
) -> None:
    await provisioner.create_database(STORE_ID)

    await provisioner.delete_database(STORE_ID)
    await provisioner.delete_database(STORE_ID)

    assert await provisioner.database_exists(STORE_ID) is False


@pytest.mark.parametrize(
    "operation", ["create_database", "database_exists", "delete_database"]
)
async def test_invalid_store_id_is_rejected_everywhere(
    provisioner: DatabaseProvisioner, operation: str
) -> None:
    with pytest.raises(InvalidStoreId):
        await getattr(provisioner, operation)("x'; --injected")
