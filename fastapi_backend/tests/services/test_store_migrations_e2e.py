"""Store migrations against a real Postgres (KAN-57).

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server whose database
name ends in ``_test``. The fixtures create their own platform database (tables from the
models) and several store databases, and drop them afterwards, so the shared test
database and its stores are never touched.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database import DefaultSessionProvider
from app.core.ids import new_id
from app.core.store_crypto import StoreSecretCodec, generate_key
from app.models.platform.store import Store, StoreStatus
from app.services import store_migrations, store_secrets
from app.services.store_migrations import (
    StoreMigrationFailed,
    StoreVersionNotRecorded,
    migrate_active_stores,
    migrate_store,
)
from commands.migrate_stores import format_report
from tests.pg_scaffold import (
    TEST_DATABASE_URL,
    create_database,
    create_platform_database,
    drop_databases,
    require_local_test_server,
    sweep_stale_databases,
    unique_name,
    url_for,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

REVISION_0002 = '''"""widgets"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("widgets", sa.Column("id", sa.Integer, primary_key=True))


def downgrade() -> None:
    op.drop_table("widgets")
'''


DATABASE_PREFIX = "ks57"


def short_name(tag: str) -> str:
    return unique_name(DATABASE_PREFIX, tag)


@pytest.fixture
async def server() -> AsyncIterator[AsyncEngine]:
    built = create_async_engine(require_local_test_server())
    await sweep_stale_databases(built, DATABASE_PREFIX)
    yield built
    await built.dispose()


@pytest.fixture
async def world(
    server: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator["World"]:
    codec = StoreSecretCodec(generate_key())
    monkeypatch.setattr(store_secrets, "get_codec", lambda: codec)
    platform_name = short_name("plat")
    platform = await create_platform_database(server, platform_name)
    created = World(server, platform, codec, [platform_name])
    try:
        yield created
    finally:
        try:
            await platform.dispose()
        finally:
            await drop_databases(server, created.databases)


class World:
    def __init__(
        self,
        server: AsyncEngine,
        platform: AsyncEngine,
        codec: StoreSecretCodec,
        databases: list[str],
    ) -> None:
        self.server = server
        self.platform = platform
        self.codec = codec
        self.databases = databases
        self.provider = DefaultSessionProvider(
            async_sessionmaker(platform, expire_on_commit=False)
        )
        self._org_id: str | None = None

    async def store_database(self, tag: str) -> str:
        name = short_name(tag)
        await create_database(self.server, name)
        self.databases.append(name)
        return name

    async def add_store(
        self,
        dsn: str | None,
        status: StoreStatus = StoreStatus.ACTIVE,
        store_id: str | None = None,
    ) -> str:
        async with self.platform.begin() as connection:
            if self._org_id is None:
                self._org_id = new_id()
                await connection.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug) VALUES (:i, 'O', :s)"
                    ),
                    {"i": self._org_id, "s": f"org-{self._org_id}"},
                )
        identifier = store_id or new_id()
        async with self.provider.session() as session:
            store = Store(
                id=identifier,
                organization_id=self._org_id,
                name="S",
                slug=f"st-{identifier}",
                status=status,
            )
            if dsn is not None:
                store_secrets.set_connection_string(store, dsn, self.codec)
            session.add(store)
            await session.commit()
        return identifier

    async def schema_version(self, store_id: str) -> int:
        async with self.platform.connect() as connection:
            return (
                await connection.execute(
                    text("SELECT schema_version FROM stores WHERE id = :i"),
                    {"i": store_id},
                )
            ).scalar_one()

    async def stamped_revision(self, database: str) -> str | None:
        engine = create_async_engine(url_for(database))
        try:
            async with engine.connect() as connection:
                exists = (
                    await connection.execute(
                        text("SELECT to_regclass('store_alembic_version')")
                    )
                ).scalar_one()
                if exists is None:
                    return None
                return (
                    await connection.execute(
                        text("SELECT version_num FROM store_alembic_version")
                    )
                ).scalar_one_or_none()
        finally:
            await engine.dispose()


async def test_fresh_store_is_migrated_and_its_version_recorded(
    world: "World", baseline: Path
):
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))

    version = await migrate_store(store_id, world.provider, script_location=baseline)

    assert version == 1
    assert await world.schema_version(store_id) == 1
    assert await world.stamped_revision(database) == "0001"


async def test_rerun_is_idempotent_and_pending_revisions_are_applied(
    world: "World", tmp_path: Path, baseline: Path
):
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))
    assert await migrate_store(store_id, world.provider, script_location=baseline) == 1
    assert await migrate_store(store_id, world.provider, script_location=baseline) == 1

    tree = make_tree(tmp_path, REVISION_0002)

    assert await migrate_store(store_id, world.provider, script_location=tree) == 2
    assert await migrate_store(store_id, world.provider, script_location=tree) == 2
    assert await world.schema_version(store_id) == 2
    assert await world.stamped_revision(database) == "0002"


async def test_batch_migrates_every_active_store_across_batches(
    world: "World", baseline: Path
):
    ids = []
    databases = []
    for tag in ("a", "b", "c"):
        database = await world.store_database(tag)
        databases.append(database)
        ids.append(await world.add_store(url_for(database)))

    report = await migrate_active_stores(
        world.provider, batch_size=2, script_location=baseline
    )

    assert report.succeeded
    assert sorted(result.store_id for result in report.migrated) == sorted(ids)
    for store_id, database in zip(ids, databases, strict=True):
        assert await world.schema_version(store_id) == 1
        assert await world.stamped_revision(database) == "0001"


async def test_non_active_stores_are_skipped_and_reported(world: "World"):
    active_db = await world.store_database("a")
    waiting_db = await world.store_database("b")
    active_id = await world.add_store(url_for(active_db))
    waiting_id = await world.add_store(
        url_for(waiting_db), status=StoreStatus.PROVISIONING
    )
    await world.add_store(None, status=StoreStatus.SUSPENDED)
    await world.add_store(None, status=StoreStatus.ARCHIVED)

    report = await migrate_active_stores(world.provider)

    assert [result.store_id for result in report.migrated] == [active_id]
    assert report.skipped == {
        StoreStatus.PROVISIONING: 1,
        StoreStatus.SUSPENDED: 1,
        StoreStatus.ARCHIVED: 1,
    }
    assert await world.schema_version(waiting_id) == 0
    assert await world.stamped_revision(waiting_db) is None
    assert "skipped 1 store(s) with status SUSPENDED (not ACTIVE)" in format_report(
        report
    )


async def test_first_failure_stops_the_run_and_leaves_later_stores_untouched(
    world: "World", baseline: Path
):
    good_db = await world.store_database("a")
    later_db = await world.store_database("c")
    ids = sorted([new_id(), new_id(), new_id()])
    await world.add_store(url_for(good_db), store_id=ids[0])
    await world.add_store(
        url_for("no_such_database_ks57", password="hunter2-secret"), store_id=ids[1]
    )
    await world.add_store(url_for(later_db), store_id=ids[2])

    report = await migrate_active_stores(
        world.provider, batch_size=1, script_location=baseline
    )

    assert not report.succeeded
    assert report.failed_store_id == ids[1]
    assert [result.store_id for result in report.migrated] == [ids[0]]
    assert await world.schema_version(ids[0]) == 1
    assert await world.schema_version(ids[2]) == 0
    assert await world.stamped_revision(later_db) is None


async def test_failure_output_never_contains_connection_secrets(world: "World"):
    store_id = await world.add_store(
        url_for("no_such_database_ks57", password="hunter2-secret")
    )

    with pytest.raises(StoreMigrationFailed) as caught:
        await migrate_store(store_id, world.provider)
    report = await migrate_active_stores(world.provider)

    printed = "\n".join(format_report(report)) + str(caught.value)
    assert store_id in printed
    for secret in ("hunter2-secret", "no_such_database_ks57", "postgresql"):
        assert secret not in printed


def _copy_baseline(root: Path) -> Path:
    tree = root / "versions"
    tree.mkdir(parents=True)
    real = Path(__file__).resolve().parents[2] / "alembic_store"
    (root / "env.py").write_text((real / "env.py").read_text())
    (root / "script.py.mako").write_text((real / "script.py.mako").read_text())
    (tree / "0001_store_baseline.py").write_text(
        (real / "versions" / "0001_store_baseline.py").read_text()
    )
    return root


@pytest.fixture
def baseline(tmp_path: Path) -> Path:
    """A store tree that stops at the 0001 baseline, whatever the real tree has added."""
    return _copy_baseline(tmp_path / "baseline_store")


def make_tree(tmp_path: Path, revision_0002: str) -> Path:
    tree = _copy_baseline(tmp_path / "alembic_store")
    (tree / "versions" / "0002_next.py").write_text(revision_0002)
    return tree


FAILING_REVISION = REVISION_0002.replace(
    '    op.create_table("widgets", sa.Column("id", sa.Integer, primary_key=True))',
    '    op.create_table("widgets", sa.Column("id", sa.Integer, primary_key=True))\n'
    '    raise RuntimeError("boom postgresql://u:hunter2@h/db")',
)


async def test_failing_revision_rolls_back_and_keeps_the_previous_version(
    world: "World", tmp_path: Path, baseline: Path
):
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider, script_location=baseline)
    tree = make_tree(tmp_path, FAILING_REVISION)

    with pytest.raises(StoreMigrationFailed) as caught:
        await migrate_store(store_id, world.provider, script_location=tree)

    assert "hunter2" not in str(caught.value)
    assert await world.stamped_revision(database) == "0001"
    assert await world.schema_version(store_id) == 1
    engine = create_async_engine(url_for(database))
    async with engine.connect() as connection:
        table = (
            await connection.execute(text("SELECT to_regclass('widgets')"))
        ).scalar_one()
    await engine.dispose()
    assert table is None


async def test_concurrent_runs_on_one_store_are_serialised(
    world: "World", tmp_path: Path
):
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))
    tree = make_tree(tmp_path, REVISION_0002)

    versions = await asyncio.gather(
        migrate_store(store_id, world.provider, script_location=tree),
        migrate_store(store_id, world.provider, script_location=tree),
    )

    assert versions == [2, 2]
    assert await world.stamped_revision(database) == "0002"


async def test_failed_version_write_is_repaired_by_the_next_run(
    world: "World", monkeypatch: pytest.MonkeyPatch, baseline: Path
):
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))

    async def broken(*_: object) -> None:
        raise ConnectionError("platform database unreachable")

    with monkeypatch.context() as patch:
        patch.setattr(store_migrations, "_record_version", broken)
        with pytest.raises(StoreVersionNotRecorded):
            await migrate_store(store_id, world.provider, script_location=baseline)
    assert await world.stamped_revision(database) == "0001"
    assert await world.schema_version(store_id) == 0

    assert await migrate_store(store_id, world.provider, script_location=baseline) == 1
    assert await world.schema_version(store_id) == 1


async def test_store_database_ahead_of_the_code_is_refused_and_never_lowered(
    world: "World", tmp_path: Path, baseline: Path
):
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))
    tree = make_tree(tmp_path, REVISION_0002)
    # A newer build migrated this store to revision 0002 and stamped schema_version 2.
    assert await migrate_store(store_id, world.provider, script_location=tree) == 2

    # An older build (only knows 0001) runs late, as in a rolling deploy.
    with pytest.raises(StoreMigrationFailed) as caught:
        await migrate_store(store_id, world.provider, script_location=baseline)

    assert caught.value.reason == "StoreSchemaAhead"
    assert await world.stamped_revision(database) == "0002"
    assert await world.schema_version(store_id) == 2


async def test_recorded_schema_version_never_goes_backwards(
    world: "World", baseline: Path
):
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET schema_version = 5 WHERE id = :i"), {"i": store_id}
        )

    assert await migrate_store(store_id, world.provider, script_location=baseline) == 1
    assert await world.schema_version(store_id) == 5


@asynccontextmanager
async def lock_held_elsewhere(database: str) -> AsyncIterator[None]:
    """Another runner holding the migration lock until the block exits."""
    locked, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        engine = create_async_engine(url_for(database))
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:k)"),
                    {"k": store_migrations._ADVISORY_LOCK_KEY},
                )
                locked.set()
                await release.wait()
        finally:
            locked.set()
            await engine.dispose()

    holder = asyncio.create_task(hold())
    try:
        await asyncio.wait_for(locked.wait(), 10)
        yield
    finally:
        release.set()
        await holder


async def test_a_long_held_lock_is_waited_for_not_failed_as_a_ddl_timeout(
    world: "World", monkeypatch: pytest.MonkeyPatch, baseline: Path
):
    # lock_timeout is 1s here; the other runner holds the lock for ~2.5s, so the wait
    # must not be governed by the DDL lock_timeout.
    monkeypatch.setattr(store_migrations, "LOCK_TIMEOUT", "1s")
    monkeypatch.setattr(store_migrations, "ADVISORY_POLL_SECONDS", 0.2)
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))
    loop = asyncio.get_running_loop()

    async with lock_held_elsewhere(database) as _:
        started = loop.time()
        migrating = asyncio.create_task(
            migrate_store(store_id, world.provider, script_location=baseline)
        )
        await asyncio.sleep(2.5)
        assert not migrating.done()
    version = await migrating

    assert loop.time() - started >= 2.4
    assert version == 1
    assert await world.schema_version(store_id) == 1


async def test_a_lock_held_past_the_wait_budget_fails_only_that_store(
    world: "World", monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(store_migrations, "ADVISORY_LOCK_WAIT_SECONDS", 1.0)
    monkeypatch.setattr(store_migrations, "ADVISORY_POLL_SECONDS", 0.2)
    database = await world.store_database("a")
    store_id = await world.add_store(url_for(database))

    async with lock_held_elsewhere(database) as _:
        with pytest.raises(StoreMigrationFailed) as caught:
            await migrate_store(store_id, world.provider)

    assert caught.value.reason == "AdvisoryLockTimeout"
    assert await world.stamped_revision(database) is None


async def test_ddl_timeouts_are_applied_after_the_lock(
    world: "World", monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(store_migrations, "LOCK_TIMEOUT", "7s")
    monkeypatch.setattr(store_migrations, "STATEMENT_TIMEOUT", "9s")
    database = await world.store_database("a")
    engine = create_async_engine(url_for(database))
    try:
        async with engine.connect() as connection:
            await store_migrations._prepare_connection(connection)
            seen = [
                (await connection.execute(text(f"SHOW {name}"))).scalar_one()
                for name in ("lock_timeout", "statement_timeout")
            ]
    finally:
        await engine.dispose()

    assert seen == ["7s", "9s"]
