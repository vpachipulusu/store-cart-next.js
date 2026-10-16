"""Provisioning job steps against a real Postgres (KAN-56).

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server whose database
name ends in ``_test``. The fixture creates its own platform database (tables from the
models); the local provisioner creates ``store_<id>`` databases on the same server, and
both are dropped afterwards. QStash is replaced by a recording enqueuer.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database import DefaultSessionProvider
from app.core.ids import new_id
from app.core.store_crypto import StoreSecretCodec, generate_key
from app.models.platform.store import Store, StoreStatus
from app.services import store_secrets
from app.services.store_migrations import StoreMigrationFailed
from app.services.store_provisioning import (
    LocalDatabaseProvisioner,
    ProvisionerNotConfigured,
    ProvisioningFailed,
    database_name_for,
)
from app.services.store_provisioning_job import (
    EnqueueFailed,
    Step,
    StepFailed,
    StepRunner,
    mark_failed,
)
from tests.pg_scaffold import (
    TEST_DATABASE_URL,
    create_platform_database,
    drop_databases,
    require_local_test_server,
    sweep_stale_databases,
    unique_name,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

DATABASE_PREFIX = "ks56"


class RecordingEnqueuer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, Step]] = []

    async def enqueue(self, store_id: str, step: Step) -> None:
        if self.fail:
            raise EnqueueFailed
        self.calls.append((store_id, step))


class World:
    def __init__(self, server: AsyncEngine, platform: AsyncEngine) -> None:
        self.server = server
        self.platform = platform
        self.provider = DefaultSessionProvider(
            async_sessionmaker(platform, expire_on_commit=False)
        )
        self.enqueuer = RecordingEnqueuer()
        self.store_ids: list[str] = []
        self.provisioning_calls = 0
        self.provisioner_error: Exception | None = None
        self.migrate_error: Exception | None = None
        self._org_id: str | None = None

    def runner(self) -> StepRunner:
        real = LocalDatabaseProvisioner(self.server)

        class Counting:
            async def create_database(inner, store_id: str) -> str:
                self.provisioning_calls += 1
                if self.provisioner_error:
                    raise self.provisioner_error
                return await real.create_database(store_id)

        async def migrate(store_id: str, provider) -> int:
            if self.migrate_error:
                raise self.migrate_error
            from app.services.store_migrations import migrate_store

            return await migrate_store(store_id, provider)

        def provisioner():
            if isinstance(self.provisioner_error, ProvisionerNotConfigured):
                raise self.provisioner_error
            return Counting()

        return StepRunner(
            provider=self.provider,
            provisioner=provisioner,  # type: ignore[arg-type]
            enqueuer=self.enqueuer,
            migrate=migrate,
        )

    async def add_store(self, status: StoreStatus = StoreStatus.PROVISIONING) -> str:
        if self._org_id is None:
            self._org_id = new_id()
            async with self.platform.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug) VALUES (:i, 'O', :s)"
                    ),
                    {"i": self._org_id, "s": f"org-{self._org_id}"},
                )
        identifier = new_id().lower()
        async with self.provider.session() as session:
            session.add(
                Store(
                    id=identifier,
                    organization_id=self._org_id,
                    name="S",
                    slug=f"st-{identifier}",
                    status=status,
                )
            )
            await session.commit()
        self.store_ids.append(identifier)
        return identifier

    async def row(self, store_id: str) -> dict[str, object]:
        async with self.platform.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT status, schema_version, database_ref, "
                    "connection_string_encrypted FROM stores WHERE id = :i"
                ),
                {"i": store_id},
            )
            return dict(result.mappings().one())


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    codec = StoreSecretCodec(generate_key())
    monkeypatch.setattr(store_secrets, "get_codec", lambda: codec)
    server = create_async_engine(require_local_test_server())
    await sweep_stale_databases(server, DATABASE_PREFIX)
    name = unique_name(DATABASE_PREFIX, "plat")
    platform = await create_platform_database(server, name)
    created = World(server, platform)
    try:
        yield created
    finally:
        try:
            cleaner = LocalDatabaseProvisioner(server)
            for store_id in created.store_ids:
                await cleaner.delete_database(store_id)
            await platform.dispose()
        finally:
            await drop_databases(server, [name])
            await server.dispose()


async def run_all(world: World, store_id: str) -> None:
    """Drive the chain the way QStash would: run a step, then the one it enqueued."""
    runner = world.runner()
    step: Step | None = Step.CREATE_DATABASE
    while step is not None:
        world.enqueuer.calls.clear()
        await runner.run(step, store_id)
        step = world.enqueuer.calls[0][1] if world.enqueuer.calls else None


async def test_the_chain_provisions_migrates_and_activates_the_store(world: World):
    store_id = await world.add_store()

    await run_all(world, store_id)

    row = await world.row(store_id)
    assert row["status"] == "ACTIVE"
    assert row["schema_version"] == 1
    assert row["database_ref"] == database_name_for(store_id)
    ciphertext = str(row["connection_string_encrypted"])
    assert ciphertext
    assert database_name_for(store_id) not in ciphertext


async def test_each_step_enqueues_the_next_one_in_order(world: World):
    store_id = await world.add_store()
    runner = world.runner()

    await runner.run(Step.CREATE_DATABASE, store_id)
    await runner.run(Step.RUN_MIGRATIONS, store_id)
    await runner.run(Step.MARK_READY, store_id)

    assert world.enqueuer.calls == [
        (store_id, Step.RUN_MIGRATIONS),
        (store_id, Step.MARK_READY),
    ]


async def test_create_database_is_idempotent_and_keeps_the_stored_secret(world: World):
    store_id = await world.add_store()
    runner = world.runner()
    await runner.run(Step.CREATE_DATABASE, store_id)
    first = await world.row(store_id)

    await runner.run(Step.CREATE_DATABASE, store_id)

    assert await world.row(store_id) == first


async def test_run_migrations_is_idempotent(world: World):
    store_id = await world.add_store()
    runner = world.runner()
    await runner.run(Step.CREATE_DATABASE, store_id)

    await runner.run(Step.RUN_MIGRATIONS, store_id)
    await runner.run(Step.RUN_MIGRATIONS, store_id)

    assert (await world.row(store_id))["schema_version"] == 1


async def test_mark_ready_is_idempotent(world: World):
    store_id = await world.add_store()
    await run_all(world, store_id)

    await world.runner().run(Step.MARK_READY, store_id)

    assert (await world.row(store_id))["status"] == "ACTIVE"


@pytest.mark.parametrize(
    "status", [StoreStatus.ACTIVE, StoreStatus.FAILED, StoreStatus.ARCHIVED]
)
async def test_steps_leave_a_store_that_is_not_provisioning_alone(
    world: World, status: StoreStatus
):
    store_id = await world.add_store(status)
    before = await world.row(store_id)

    for step in Step:
        await world.runner().run(step, store_id)

    assert await world.row(store_id) == before
    assert world.provisioning_calls == 0
    assert world.enqueuer.calls == []


async def test_a_step_for_an_unknown_store_is_a_no_op(world: World):
    await world.runner().run(Step.CREATE_DATABASE, "abcdefgh12345678abcdefgh")

    assert world.provisioning_calls == 0


async def test_mark_ready_before_migrations_asks_for_a_retry(world: World):
    store_id = await world.add_store()

    with pytest.raises(StepFailed):
        await world.runner().run(Step.MARK_READY, store_id)

    assert (await world.row(store_id))["status"] == "PROVISIONING"


async def test_a_provider_failure_is_retried_and_leaves_the_store_provisioning(
    world: World,
):
    store_id = await world.add_store()
    world.provisioner_error = ProvisioningFailed(store_id)

    with pytest.raises(StepFailed):
        await world.runner().run(Step.CREATE_DATABASE, store_id)

    row = await world.row(store_id)
    assert row["status"] == "PROVISIONING"
    assert row["connection_string_encrypted"] is None
    assert world.enqueuer.calls == []


async def test_a_missing_provider_configuration_fails_the_store_without_retry(
    world: World,
):
    store_id = await world.add_store()
    world.provisioner_error = ProvisionerNotConfigured("neon", ("NEON_API_KEY",))

    await world.runner().run(Step.CREATE_DATABASE, store_id)

    assert (await world.row(store_id))["status"] == "FAILED"
    assert world.enqueuer.calls == []


async def test_a_migration_failure_is_retried(world: World):
    store_id = await world.add_store()
    runner = world.runner()
    await runner.run(Step.CREATE_DATABASE, store_id)
    world.migrate_error = StoreMigrationFailed(store_id, "OperationalError")

    with pytest.raises(StepFailed):
        await runner.run(Step.RUN_MIGRATIONS, store_id)

    assert (await world.row(store_id))["status"] == "PROVISIONING"


async def test_a_failed_enqueue_of_the_next_step_asks_for_a_retry(world: World):
    store_id = await world.add_store()
    world.enqueuer.fail = True

    with pytest.raises(StepFailed):
        await world.runner().run(Step.CREATE_DATABASE, store_id)

    # The step itself completed, so the retry only has to publish again.
    assert (await world.row(store_id))["database_ref"] == database_name_for(store_id)


async def test_mark_failed_only_changes_a_provisioning_store(world: World):
    provisioning = await world.add_store()
    active = await world.add_store(StoreStatus.ACTIVE)

    assert await mark_failed(world.provider, provisioning) is True
    assert await mark_failed(world.provider, provisioning) is False
    assert await mark_failed(world.provider, active) is False

    assert (await world.row(provisioning))["status"] == "FAILED"
    assert (await world.row(active))["status"] == "ACTIVE"
