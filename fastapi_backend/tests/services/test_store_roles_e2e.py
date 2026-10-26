"""One role per store database on a real Postgres (KAN-238, ADR-005).

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local ``*_test`` database (see
``tests/pg_scaffold.py``); CI runs it on its Postgres 17 container. The provisioning role
is a fresh non-superuser with CREATEDB and CREATEROLE, the shape of Neon's project role,
so the SQL is proven without superuser rights.

Every name carries the ``k238`` prefix, the epoch and a random part: teardown drops what
a test created, and ``sweep`` removes what a killed run left behind (over an hour old).
"""

import re
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database import DefaultSessionProvider
from app.core.ids import new_id
from app.core.store_crypto import StoreSecretCodec, generate_key
from app.models.platform.store import Store, StoreStatus
from app.services import store_secrets
from app.services.store_migrations import migrate_store
from app.services.store_provisioning import LocalDatabaseProvisioner, database_name_for
from app.services.store_role_backfill import (
    BackfillFailure,
    Outcome,
    backfill_store_role,
    backfill_store_roles,
)
from app.services.store_roles import release_store_database
from app.services.store_sessions import open_admin_connection, open_store_session
from commands.backfill_store_roles import format_report
from tests.pg_scaffold import (
    STALE_AFTER_SECONDS,
    TEST_DATABASE_URL,
    create_platform_database,
    drop_databases,
    quote,
    require_local_test_server,
    unique_name,
    url_for,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

PREFIX = "k238"
# Store ids: k238<epoch><6 random>, so role and database are store_k238<epoch>...
_STALE_STORE = re.compile(rf"^store_{PREFIX}(\d{{10}})[0-9a-z]{{6}}$")
_STALE_ADMIN = re.compile(rf"^{PREFIX}adm_(\d{{10}})_[0-9a-z]{{6}}$")
_STALE_PLATFORM = re.compile(rf"^{PREFIX}_(\d{{10}})_[0-9a-z]{{6}}_\w+$")
INVALID_PASSWORD = "28P01"
INSUFFICIENT_PRIVILEGE = "42501"


def new_store_id() -> str:
    return f"{PREFIX}{int(time.time())}{secrets.token_hex(3)}"


def is_stale(name: str, pattern: re.Pattern[str], now: float) -> bool:
    match = pattern.fullmatch(name)
    return match is not None and now - int(match.group(1)) > STALE_AFTER_SECONDS


async def sweep(server: AsyncEngine) -> None:
    """Drop the databases and roles of a killed run (databases first: roles own them)."""
    now = time.time()
    async with server.connect() as connection:
        databases = list(
            (
                await connection.execute(text("SELECT datname FROM pg_database"))
            ).scalars()
        )
        roles = list(
            (await connection.execute(text("SELECT rolname FROM pg_roles"))).scalars()
        )
    await drop_databases(
        server,
        [
            name
            for name in databases
            if is_stale(name, _STALE_STORE, now) or is_stale(name, _STALE_PLATFORM, now)
        ],
    )
    stale_stores = [name for name in roles if is_stale(name, _STALE_STORE, now)]
    stale_admins = [name for name in roles if is_stale(name, _STALE_ADMIN, now)]
    await drop_roles(server, [*stale_stores, *stale_admins])


async def drop_roles(server: AsyncEngine, names: list[str]) -> None:
    async with server.execution_options(isolation_level="AUTOCOMMIT").connect() as c:
        for name in names:
            await c.execute(text(f"DROP ROLE IF EXISTS {quote(name)}"))


async def sqlstate_of_connecting(url: str) -> str | None:
    """None when the URL connects, else the SQLSTATE Postgres refused it with."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return None
    except DBAPIError as exc:
        return getattr(exc.orig, "sqlstate", None)
    finally:
        await engine.dispose()


async def scalar_as(url: str, sql: str) -> object:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text(sql))
    finally:
        await engine.dispose()


@dataclass
class Cluster:
    """The superuser server engine, a Neon-like provisioning role and what to drop."""

    server: AsyncEngine
    admin_name: str
    admin_url: str
    admin: AsyncEngine
    store_ids: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    extra_roles: list[str] = field(default_factory=list)

    def provisioner(self) -> LocalDatabaseProvisioner:
        return LocalDatabaseProvisioner(self.admin)

    def store_id(self) -> str:
        store_id = new_store_id()
        self.store_ids.append(store_id)
        return store_id


@pytest.fixture
async def cluster() -> AsyncIterator[Cluster]:
    server = create_async_engine(require_local_test_server())
    await sweep(server)
    admin_name = f"{PREFIX}adm_{int(time.time())}_{secrets.token_hex(3)}"
    admin_password = secrets.token_urlsafe(24)
    async with server.execution_options(isolation_level="AUTOCOMMIT").connect() as c:
        await c.exec_driver_sql(
            f"CREATE ROLE {quote(admin_name)} WITH LOGIN CREATEDB CREATEROLE "
            f"PASSWORD '{admin_password}'"
        )
    admin_url = (
        make_url(url_for(make_url(require_local_test_server()).database or ""))
        .set(username=admin_name, password=admin_password)
        .render_as_string(hide_password=False)
    )
    admin = create_async_engine(admin_url)
    built = Cluster(server, admin_name, admin_url, admin)
    try:
        yield built
    finally:
        try:
            await admin.dispose()
            await drop_databases(
                server,
                [database_name_for(sid) for sid in built.store_ids] + built.databases,
            )
            await drop_roles(
                server, [database_name_for(sid) for sid in built.store_ids]
            )
            await drop_roles(server, [*built.extra_roles, admin_name])
        finally:
            await server.dispose()


# --- Acceptance criterion 2: one store's credential cannot open another store ---------


async def test_a_store_credential_cannot_connect_to_another_store_database(
    cluster: Cluster,
) -> None:
    provisioner = cluster.provisioner()
    store_a, store_b = cluster.store_id(), cluster.store_id()
    dsn_a = await provisioner.create_database(store_a)
    dsn_b = await provisioner.create_database(store_b)
    a_on_b = make_url(dsn_a).set(database=database_name_for(store_b))

    refused = await sqlstate_of_connecting(a_on_b.render_as_string(False))

    assert refused == INSUFFICIENT_PRIVILEGE
    assert await scalar_as(dsn_a, "SELECT current_user") == database_name_for(store_a)
    assert await scalar_as(dsn_b, "SELECT current_user") == database_name_for(store_b)


async def test_a_rerun_rotates_the_password_and_the_old_one_stops_working(
    cluster: Cluster,
) -> None:
    provisioner = cluster.provisioner()
    store_id = cluster.store_id()
    first = await provisioner.create_database(store_id)
    engine = create_async_engine(first)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE kept (id int)"))
    finally:
        await engine.dispose()

    second = await provisioner.create_database(store_id)

    assert await sqlstate_of_connecting(first) == INVALID_PASSWORD
    assert await scalar_as(second, "SELECT count(*) FROM kept") == 0


async def test_only_the_store_role_may_connect_and_it_holds_no_privileged_attribute(
    cluster: Cluster,
) -> None:
    store_id = cluster.store_id()
    name = database_name_for(store_id)
    await cluster.provisioner().create_database(store_id)

    async with cluster.server.connect() as connection:
        role = (
            await connection.execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                    "rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = :n"
                ),
                {"n": name},
            )
        ).one()
        owner = await connection.scalar(
            text("SELECT datdba::regrole::text FROM pg_database WHERE datname = :n"),
            {"n": name},
        )
        public_connect = await connection.scalar(
            text(
                "SELECT bool_or(a.grantee = 0 AND a.privilege_type = 'CONNECT') "
                "FROM pg_database d, aclexplode(d.datacl) a WHERE d.datname = :n"
            ),
            {"n": name},
        )
        store_connect = await connection.scalar(
            text(
                "SELECT has_database_privilege(CAST(:n AS text), CAST(:n AS text), 'CONNECT, TEMPORARY')"
            ),
            {"n": name},
        )

    assert tuple(role) == (False, False, False, False, False, True)
    # The database stays with the provisioning role (what Neon records); the store role
    # uses it through explicit grants.
    assert owner == cluster.admin_name
    assert public_connect is False
    assert store_connect is True


async def test_the_provisioning_role_keeps_access_through_membership(
    cluster: Cluster,
) -> None:
    store_id = cluster.store_id()
    await cluster.provisioner().create_database(store_id)
    admin_on_store = make_url(cluster.admin_url).set(
        database=database_name_for(store_id)
    )

    assert await sqlstate_of_connecting(admin_on_store.render_as_string(False)) is None


async def test_a_store_role_reads_nothing_in_a_database_it_does_not_own(
    cluster: Cluster,
) -> None:
    store_id = cluster.store_id()
    dsn = await cluster.provisioner().create_database(store_id)
    platform_name = unique_name(PREFIX, "plat")
    cluster.databases.append(platform_name)
    platform = await create_platform_database(cluster.server, platform_name)
    await platform.dispose()
    on_platform = make_url(dsn).set(database=platform_name).render_as_string(False)

    engine = create_async_engine(on_platform)
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError) as caught:
                await connection.execute(text("SELECT count(*) FROM stores"))
    finally:
        await engine.dispose()

    assert getattr(caught.value.orig, "sqlstate", None) == INSUFFICIENT_PRIVILEGE


async def use_store_database(dsn: str, table: str) -> None:
    """Connect as the store role, create a table and a temporary table."""
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"CREATE TABLE {table} (id int)"))
            await connection.execute(
                text(f"CREATE TEMP TABLE scratch_{table} (id int)")
            )
    finally:
        await engine.dispose()


async def test_access_does_not_depend_on_who_owns_the_database(
    cluster: Cluster,
) -> None:
    """Neon's control plane may (re)set the owner at any time; access must survive it."""
    store_id = cluster.store_id()
    name = database_name_for(store_id)
    dsn = await cluster.provisioner().create_database(store_id)
    third = f"{PREFIX}adm_{int(time.time())}_{secrets.token_hex(3)}"
    cluster.extra_roles.append(third)
    superuser = cluster.server.execution_options(isolation_level="AUTOCOMMIT")
    async with superuser.connect() as connection:
        await connection.exec_driver_sql(f"CREATE ROLE {quote(third)} NOLOGIN")
        await connection.exec_driver_sql(
            f"ALTER DATABASE {quote(name)} OWNER TO {quote(third)}"
        )

    await use_store_database(dsn, "while_owned_elsewhere")

    async with superuser.connect() as connection:
        await connection.exec_driver_sql(
            f"ALTER DATABASE {quote(name)} OWNER TO {quote(cluster.admin_name)}"
        )
    await use_store_database(dsn, "after_owner_restored")
    other = cluster.store_id()
    other_dsn = await cluster.provisioner().create_database(other)
    other_here = make_url(other_dsn).set(database=name).render_as_string(False)
    assert await sqlstate_of_connecting(other_here) == INSUFFICIENT_PRIVILEGE


async def test_a_reused_database_from_before_kan238_is_handed_to_the_store_role(
    cluster: Cluster,
) -> None:
    """A re-provision reuses the orphan database of a failed run, built as the shared role."""
    store_id = cluster.store_id()
    name = database_name_for(store_id)
    async with cluster.admin.execution_options(
        isolation_level="AUTOCOMMIT"
    ).connect() as connection:
        await connection.exec_driver_sql(f"CREATE DATABASE {quote(name)}")
    shared = create_async_engine(
        make_url(cluster.admin_url).set(database=name).render_as_string(False)
    )
    try:
        async with shared.begin() as connection:
            for statement in LEGACY_SCHEMA:
                await connection.exec_driver_sql(statement)
    finally:
        await shared.dispose()

    dsn = await cluster.provisioner().create_database(store_id)

    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE store_alembic_version SET version_num = '0002'")
            )
            await connection.execute(text("ALTER TABLE products ADD COLUMN x int"))
    finally:
        await engine.dispose()


async def test_delete_drops_the_database_and_the_role(cluster: Cluster) -> None:
    provisioner = cluster.provisioner()
    store_id = cluster.store_id()
    await provisioner.create_database(store_id)

    await provisioner.delete_database(store_id)
    await provisioner.delete_database(store_id)

    async with cluster.server.connect() as connection:
        role = await connection.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :n"),
            {"n": database_name_for(store_id)},
        )
    assert role is None
    assert await provisioner.database_exists(store_id) is False


# --- Acceptance criterion 3: existing stores move with the backfill -----------------

LEGACY_SCHEMA = (
    "CREATE TYPE mood AS ENUM ('calm', 'busy')",
    (
        "CREATE TABLE products (id serial PRIMARY KEY, "
        "n int GENERATED ALWAYS AS IDENTITY, mood mood)"
    ),
    "CREATE TABLE store_alembic_version (version_num varchar(32) PRIMARY KEY)",
    "INSERT INTO store_alembic_version VALUES ('0001')",
    "INSERT INTO products (mood) VALUES ('calm')",
    "CREATE VIEW calm_products AS SELECT id FROM products WHERE mood = 'calm'",
    "CREATE FUNCTION twice(x int) RETURNS int LANGUAGE sql AS 'SELECT x * 2'",
    "CREATE SEQUENCE free_counter",
    "CREATE SCHEMA reports",
    "CREATE TABLE reports.daily (day date)",
)


@dataclass
class Legacy:
    """A store built before KAN-238: its database and string use the shared role."""

    store_id: str
    provider: DefaultSessionProvider
    other_database: str
    shared_dsn: str


@pytest.fixture
async def legacy(
    cluster: Cluster, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Legacy]:
    """``LEGACY_SCHEMA``, or the statements given by indirect parametrization."""
    schema: tuple[str, ...] = getattr(request, "param", LEGACY_SCHEMA)
    codec = StoreSecretCodec(generate_key())
    monkeypatch.setattr(store_secrets, "get_codec", lambda: codec)
    platform_name = unique_name(PREFIX, "plat")
    cluster.databases.append(platform_name)
    platform = await create_platform_database(cluster.server, platform_name)
    store_id = cluster.store_id()
    name = database_name_for(store_id)
    # Another database the shared role owns: the backfill must leave it alone.
    other = unique_name(PREFIX, "other")
    cluster.databases.append(other)
    async with cluster.admin.execution_options(
        isolation_level="AUTOCOMMIT"
    ).connect() as connection:
        await connection.exec_driver_sql(f"CREATE DATABASE {quote(name)}")
        await connection.exec_driver_sql(f"CREATE DATABASE {quote(other)}")
    shared_dsn = make_url(cluster.admin_url).set(database=name).render_as_string(False)
    store_engine = create_async_engine(shared_dsn)
    async with store_engine.begin() as connection:
        for statement in schema:
            await connection.exec_driver_sql(statement)
    await store_engine.dispose()
    provider = DefaultSessionProvider(
        async_sessionmaker(platform, expire_on_commit=False)
    )
    org_id = new_id()
    async with platform.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:i, 'O', :s)"),
            {"i": org_id, "s": f"org-{org_id}"},
        )
    async with provider.session() as session:
        store = Store(
            id=store_id,
            organization_id=org_id,
            name="S",
            slug=f"st-{store_id}",
            status=StoreStatus.ACTIVE,
        )
        store_secrets.set_connection_string(store, shared_dsn)
        session.add(store)
        await session.commit()
    try:
        yield Legacy(store_id, provider, other, shared_dsn)
    finally:
        await platform.dispose()


async def stored_dsn(legacy: Legacy) -> str:
    async with legacy.provider.session() as session:
        store = await session.get(Store, legacy.store_id)
        assert store is not None
        dsn = store_secrets.reveal_connection_string(store)
    assert dsn is not None
    return dsn


async def test_backfill_moves_every_object_to_the_store_role(
    cluster: Cluster, legacy: Legacy
) -> None:
    name = database_name_for(legacy.store_id)

    report = await backfill_store_roles(legacy.provider)

    assert report.moved == (legacy.store_id,)
    assert report.succeeded
    dsn = await stored_dsn(legacy)
    assert make_url(dsn).username == name
    owners = await scalar_as(
        dsn,
        "SELECT array_agg(DISTINCT pg_get_userbyid(relowner)::text) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname IN ('public', 'reports')",
    )
    assert owners == [name]
    leftovers = await scalar_as(
        dsn,
        "SELECT count(*) FROM pg_shdepend WHERE deptype = 'o' "
        f"AND refobjid = '{cluster.admin_name}'::regrole "
        "AND dbid = (SELECT oid FROM pg_database WHERE datname = current_database())",
    )
    assert leftovers == 0
    async with open_store_session(legacy.store_id, legacy.provider) as session:
        assert (
            await session.execute(text("SELECT twice(count(*)::int) FROM products"))
        ).scalar_one() == 2
        await session.execute(text("INSERT INTO products (mood) VALUES ('busy')"))
        await session.execute(text("CREATE TABLE added_after (id int)"))
        await session.commit()


async def test_backfill_revokes_public_connect_and_changes_no_database_owner(
    cluster: Cluster, legacy: Legacy
) -> None:
    await backfill_store_roles(legacy.provider)

    async with cluster.server.connect() as connection:
        owners = dict(
            (
                await connection.execute(
                    text(
                        "SELECT datname, datdba::regrole::text FROM pg_database "
                        "WHERE datname IN (:a, :b)"
                    ),
                    {
                        "a": database_name_for(legacy.store_id),
                        "b": legacy.other_database,
                    },
                )
            ).all()
        )
    assert owners == {
        database_name_for(legacy.store_id): cluster.admin_name,
        legacy.other_database: cluster.admin_name,
    }
    # The store database now refuses every other store's role.
    other_store = cluster.store_id()
    other_dsn = await cluster.provisioner().create_database(other_store)
    other_on_this = make_url(other_dsn).set(database=database_name_for(legacy.store_id))
    assert (
        await sqlstate_of_connecting(other_on_this.render_as_string(False))
        == INSUFFICIENT_PRIVILEGE
    )


async def test_backfill_rerun_skips_a_store_already_on_its_role(
    legacy: Legacy,
) -> None:
    await backfill_store_roles(legacy.provider)
    moved_dsn = await stored_dsn(legacy)

    report = await backfill_store_roles(legacy.provider)

    assert report.moved == ()
    assert report.skipped == (legacy.store_id,)
    assert await stored_dsn(legacy) == moved_dsn
    assert (
        await backfill_store_role(legacy.store_id, legacy.provider) == Outcome.SKIPPED
    )


async def test_backfill_report_never_shows_a_connection_string(
    cluster: Cluster, legacy: Legacy
) -> None:
    report = await backfill_store_roles(legacy.provider)

    printed = "\n".join(format_report(report))
    assert legacy.store_id in printed
    assert "postgresql" not in printed
    assert cluster.admin_name not in printed


async def test_backfill_stops_at_a_store_whose_string_names_another_database(
    cluster: Cluster, legacy: Legacy
) -> None:
    async with legacy.provider.session() as session:
        store = await session.get(Store, legacy.store_id)
        assert store is not None
        wrong = make_url(cluster.admin_url).set(database=legacy.other_database)
        store_secrets.set_connection_string(store, wrong.render_as_string(False))
        await session.commit()

    report = await backfill_store_roles(
        legacy.provider, store_ids=[legacy.store_id, "never-reached"]
    )

    assert report.failures == (
        BackfillFailure(legacy.store_id, "StoreDatabaseUnavailable"),
    )
    assert report.stopped is True
    assert report.moved == ()


async def test_backfill_skips_a_store_with_no_database_yet(legacy: Legacy) -> None:
    async with legacy.provider.session() as session:
        store = await session.get(Store, legacy.store_id)
        assert store is not None
        store.connection_string_encrypted = None
        await session.commit()

    report = await backfill_store_roles(legacy.provider, store_ids=[legacy.store_id])

    assert report.skipped == (legacy.store_id,)
    assert report.succeeded


async def test_backfill_of_an_unknown_store_fails_typed(legacy: Legacy) -> None:
    report = await backfill_store_roles(legacy.provider, store_ids=["k238nosuchstore"])

    assert report.failures == (BackfillFailure("k238nosuchstore", "StoreNotFound"),)


# --- KAN-238 review follow-ups -------------------------------------------------------


async def test_dry_run_lists_the_store_and_changes_nothing(
    cluster: Cluster, legacy: Legacy
) -> None:
    report = await backfill_store_roles(legacy.provider, dry_run=True)

    assert report.would_move == (legacy.store_id,)
    assert report.moved == ()
    assert await stored_dsn(legacy) == legacy.shared_dsn
    async with cluster.server.connect() as connection:
        role = await connection.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :n"),
            {"n": database_name_for(legacy.store_id)},
        )
    assert role is None


async def test_the_default_selection_leaves_archived_stores_alone(
    legacy: Legacy,
) -> None:
    async with legacy.provider.session() as session:
        store = await session.get(Store, legacy.store_id)
        assert store is not None
        store.status = StoreStatus.ARCHIVED
        await session.commit()

    report = await backfill_store_roles(legacy.provider)

    assert (report.moved, report.skipped, report.failures) == ((), (), ())


async def test_continue_on_error_moves_the_rest_and_still_fails(
    legacy: Legacy,
) -> None:
    report = await backfill_store_roles(
        legacy.provider,
        store_ids=["k238nosuchstore", legacy.store_id],
        continue_on_error=True,
    )

    assert report.moved == (legacy.store_id,)
    assert report.failures == (BackfillFailure("k238nosuchstore", "StoreNotFound"),)
    assert report.stopped is False
    assert not report.succeeded


async def test_an_object_kind_it_cannot_move_rolls_the_store_back(
    cluster: Cluster, legacy: Legacy
) -> None:
    engine = create_async_engine(legacy.shared_dsn)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                'CREATE COLLATION german (provider = libc, locale = "C")'
            )
    finally:
        await engine.dispose()

    report = await backfill_store_roles(legacy.provider)

    assert report.failures == (BackfillFailure(legacy.store_id, "OwnershipNotMoved"),)
    assert await stored_dsn(legacy) == legacy.shared_dsn
    async with cluster.server.connect() as connection:
        role = await connection.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :n"),
            {"n": database_name_for(legacy.store_id)},
        )
    assert role is None


async def test_tables_created_between_the_ddl_and_the_row_flip_are_moved_too(
    cluster: Cluster, legacy: Legacy
) -> None:
    """A migration on the old string can run after the DDL commits, before the flip."""
    calls = 0

    @asynccontextmanager
    async def migration_in_the_gap(uri: str) -> AsyncIterator[Any]:
        nonlocal calls
        calls += 1
        if calls == 2:  # the post-flip pass: the "migration" ran just before it
            late = create_async_engine(legacy.shared_dsn)
            try:
                async with late.begin() as connection:
                    await connection.exec_driver_sql(
                        "CREATE TABLE late_arrival (id int)"
                    )
            finally:
                await late.dispose()
        async with open_admin_connection(uri) as connection:
            yield connection

    report = await backfill_store_roles(
        legacy.provider, admin_connection=migration_in_the_gap
    )

    assert report.moved == (legacy.store_id,)
    owner = await scalar_as(
        await stored_dsn(legacy),
        "SELECT pg_get_userbyid(relowner)::text FROM pg_class "
        "WHERE relname = 'late_arrival'",
    )
    assert owner == database_name_for(legacy.store_id)


async def test_release_hands_the_objects_back_and_drops_the_role(
    cluster: Cluster,
) -> None:
    """The SQL the Neon provisioner runs before deleting a store database."""
    store_id = cluster.store_id()
    name = database_name_for(store_id)
    dsn = await cluster.provisioner().create_database(store_id)
    await use_store_database(dsn, "owned_by_store")
    admin_on_store = make_url(cluster.admin_url).set(database=name)

    async with open_admin_connection(admin_on_store.render_as_string(False)) as c:
        await release_store_database(c, name)
        owner = await c.scalar(
            text(
                "SELECT pg_get_userbyid(relowner)::text FROM pg_class "
                "WHERE relname = 'owned_by_store'"
            )
        )

    assert owner == cluster.admin_name
    async with cluster.server.connect() as connection:
        role = await connection.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}
        )
    assert role is None


def extended_store_tree(root: Path) -> Path:
    """The real store tree plus one revision that alters a real table."""
    real = Path(__file__).resolve().parents[2] / "alembic_store"
    tree = root / "alembic_store"
    (tree / "versions").mkdir(parents=True)
    (tree / "env.py").write_text((real / "env.py").read_text())
    (tree / "script.py.mako").write_text((real / "script.py.mako").read_text())
    revisions = sorted((real / "versions").glob("[0-9]*.py"))
    for revision in revisions:
        (tree / "versions" / revision.name).write_text(revision.read_text())
    head = revisions[-1].name.split("_", 1)[0]
    (tree / "versions" / "9999_kan238_probe.py").write_text(
        f'''"""KAN-238 probe: a later revision applied as the store role."""

import sqlalchemy as sa
from alembic import op

revision = "9999"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("kan238_probe", sa.Integer()))
    op.create_table("kan238_probe", sa.Column("id", sa.Integer, primary_key=True))


def downgrade() -> None:
    op.drop_table("kan238_probe")
    op.drop_column("products", "kan238_probe")
'''
    )
    return tree


@pytest.mark.parametrize("legacy", [()], indirect=True)
async def test_a_later_real_revision_applies_as_the_store_role_after_the_backfill(
    legacy: Legacy, tmp_path: Path
) -> None:
    # Built the old way: the real store tree applied as the shared role.
    await migrate_store(legacy.store_id, legacy.provider)
    await backfill_store_roles(legacy.provider)

    version = await migrate_store(
        legacy.store_id,
        legacy.provider,
        script_location=extended_store_tree(tmp_path),
    )

    dsn = await stored_dsn(legacy)
    assert make_url(dsn).username == database_name_for(legacy.store_id)
    assert version > 1
    assert await scalar_as(
        dsn,
        "SELECT pg_get_userbyid(relowner)::text FROM pg_class "
        "WHERE relname = 'kan238_probe'",
    ) == database_name_for(legacy.store_id)
