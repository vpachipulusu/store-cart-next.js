"""Tenant isolation suite (KAN-58, ADR-005): no one reads or writes another tenant's data.

Two organisations with three stores each, every store on its own real Postgres database
(created by the local provisioner, connection string encrypted with the store id as AAD,
reached only through ``open_store_session``). Two layers are proven:

* API: a user of one organisation gets the same 404 for another organisation's ids as for
  ids that do not exist, and nothing changes in the other organisation.
* Data: rows written through one store session never appear in any other store database
  (other organisation or sibling store), a connection string cannot be replayed under
  another store id, and the migration runner stays inside the database it was told to.

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server whose database
name ends in ``_test``. It builds its own platform database (tables from the models) and
store databases, and drops them afterwards; the shared test database is not touched.
"""

import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import app.models.platform  # noqa: F401  (registers every table on Base.metadata)
from app.api.auth import get_session_identity
from app.api.deps import get_session_provider
from app.core.base import Base
from app.core.database import DefaultSessionProvider
from app.core.firebase import VerifiedIdentity
from app.core.ids import new_id
from app.core.store_crypto import StoreSecretCodec, StoreSecretUnavailable, generate_key
from app.main import create_app
from app.models.platform.store import Store
from app.services import store_secrets
from app.services.store_migrations import (
    StoreMigrationFailed,
    migrate_active_stores,
    migrate_store,
)
from app.services.store_provisioning import LocalDatabaseProvisioner, database_name_for
from app.services.store_sessions import (
    StoreDatabaseUnavailable,
    StoreNotFound,
    open_store_session,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
KEY = "test-only-internal-service-key-not-for-deployment"
STORE_SLUGS = ("north", "south", "east")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

WIDGETS_REVISION = '''"""widgets"""

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

COPY_CIPHERTEXT = (
    "UPDATE stores SET connection_string_encrypted = "
    "(SELECT connection_string_encrypted FROM stores WHERE id = :donor) "
    "WHERE id = :victim"
)


def url_for(database: str) -> str:
    assert TEST_DATABASE_URL is not None
    return make_url(TEST_DATABASE_URL).set(database=database).render_as_string(False)


@dataclass
class Tenant:
    """One organisation: its id and its stores' ids by slug."""

    org_id: str
    stores: dict[str, str] = field(default_factory=dict)


class World:
    """Platform database, provisioner and the two tenants of one test."""

    def __init__(self, server: AsyncEngine, platform: AsyncEngine, names: list[str]):
        self.server = server
        self.platform = platform
        self.databases = names
        self.codec = StoreSecretCodec(generate_key())
        self.provider = DefaultSessionProvider(
            async_sessionmaker(platform, expire_on_commit=False)
        )
        self.provisioner = LocalDatabaseProvisioner(server)
        self.provisioned: list[str] = []
        self.a = Tenant(new_id())
        self.b = Tenant(new_id())

    def every_store(self) -> list[str]:
        return [sid for tenant in (self.a, self.b) for sid in tenant.stores.values()]

    async def seed(self) -> None:
        users = {name: new_id() for name in ("alice", "amy", "bob", "carol", "eve")}
        memberships = [
            ("alice", self.a, "OWNER"),
            ("amy", self.a, "STAFF"),
            ("bob", self.b, "OWNER"),
            ("carol", self.a, "STAFF"),
            ("carol", self.b, "OWNER"),
        ]
        async with self.platform.begin() as connection:
            for name, user_id in users.items():
                await connection.execute(
                    text(
                        "INSERT INTO users (id, firebase_uid, email, email_verified) "
                        "VALUES (:id, :uid, :email, true)"
                    ),
                    {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@x.test"},
                )
            for label, tenant in (("a", self.a), ("b", self.b)):
                await connection.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug) VALUES (:i, :n, :s)"
                    ),
                    {"i": tenant.org_id, "n": f"Org {label}", "s": f"org-{label}"},
                )
                for slug in STORE_SLUGS:
                    tenant.stores[slug] = new_id()
                    await connection.execute(
                        text(
                            "INSERT INTO stores (id, organization_id, name, slug, status) "
                            "VALUES (:id, :org, :n, :s, 'ACTIVE')"
                        ),
                        {
                            "id": tenant.stores[slug],
                            "org": tenant.org_id,
                            "n": f"{label} {slug}",
                            "s": f"{label}-{slug}",
                        },
                    )
            for name, tenant, role in memberships:
                await connection.execute(
                    text(
                        "INSERT INTO memberships (id, organization_id, user_id, role) "
                        "VALUES (:id, :o, :u, :r)"
                    ),
                    {"id": new_id(), "o": tenant.org_id, "u": users[name], "r": role},
                )

    async def provision(self, store_id: str) -> str:
        """Create the store's own database, encrypt its string onto the row, add a marker."""
        dsn = await self.provisioner.create_database(store_id)
        self.provisioned.append(store_id)
        async with self.provider.session() as session:
            store = await session.get(Store, store_id)
            assert store is not None
            store_secrets.set_connection_string(store, dsn, self.codec)
            await session.commit()
        async with open_store_session(store_id, self.provider) as session:
            await session.execute(text("CREATE TABLE marker (owner text NOT NULL)"))
            await session.execute(
                text("INSERT INTO marker (owner) VALUES (:o)"), {"o": store_id}
            )
            await session.commit()
        return dsn

    async def provision_all(self) -> None:
        for store_id in self.every_store():
            await self.provision(store_id)

    async def markers(self, store_id: str) -> list[str]:
        async with open_store_session(store_id, self.provider) as session:
            rows = await session.execute(text("SELECT owner FROM marker"))
            return [row[0] for row in rows]

    async def platform_value(self, sql: str, **params: str) -> object:
        async with self.platform.connect() as connection:
            return (await connection.execute(text(sql), params)).scalar_one()

    async def raw_markers(self, store_id: str) -> list[str]:
        """Marker rows read over a direct admin connection, bypassing the registry."""
        engine = create_async_engine(url_for(database_name_for(store_id)))
        try:
            async with engine.connect() as connection:
                rows = await connection.execute(text("SELECT owner FROM marker"))
                return [row[0] for row in rows]
        finally:
            await engine.dispose()

    async def store_value(self, store_id: str, sql: str) -> object:
        async with open_store_session(store_id, self.provider) as session:
            return (await session.execute(text(sql))).scalar_one()

    async def copy_ciphertext(self, donor: str, victim: str) -> None:
        async with self.platform.begin() as connection:
            await connection.execute(
                text(COPY_CIPHERTEXT), {"donor": donor, "victim": victim}
            )


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    assert TEST_DATABASE_URL is not None
    assert (make_url(TEST_DATABASE_URL).database or "").endswith("_test")
    server = create_async_engine(TEST_DATABASE_URL)
    platform_name = f"ks58_{new_id()[:8]}_plat"
    admin = server.execution_options(isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{platform_name}"'))
    platform = create_async_engine(url_for(platform_name))
    async with platform.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    built = World(server, platform, [platform_name])
    monkeypatch.setattr(store_secrets, "get_codec", lambda: built.codec)
    await built.seed()
    yield built
    await platform.dispose()
    for store_id in built.provisioned:
        await built.provisioner.delete_database(store_id)
    async with admin.connect() as connection:
        for name in built.databases:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )
    await server.dispose()


@pytest.fixture
async def client(world: World) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_session_provider] = lambda: world.provider

    async def identity(
        x_test_uid: Annotated[str | None, Header()] = None,
    ) -> VerifiedIdentity:
        if x_test_uid is None:
            raise HTTPException(401, "Invalid authentication")
        return VerifiedIdentity(
            x_test_uid, f"{x_test_uid}@x.test", True, int(time.time())
        )

    app.dependency_overrides[get_session_identity] = identity
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Internal-Key": KEY}
    ) as http:
        yield http


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}"}


def same_failure(response: Response, reference: Response) -> None:
    """Both responses are indistinguishable: status, body and cache header."""
    assert response.status_code == reference.status_code
    assert response.json() == reference.json()
    assert response.headers.get("cache-control") == reference.headers.get(
        "cache-control"
    )


# --- API: organisations ---------------------------------------------------------


async def test_listing_returns_only_the_callers_organisation_and_its_stores(
    client: AsyncClient, world: World
) -> None:
    alice = (await client.get("/v1/organizations", headers=as_user("alice"))).json()
    bob = (await client.get("/v1/organizations", headers=as_user("bob"))).json()
    eve = (await client.get("/v1/organizations", headers=as_user("eve"))).json()

    assert [org["id"] for org in alice["data"]] == [world.a.org_id]
    assert [org["id"] for org in bob["data"]] == [world.b.org_id]
    assert eve["data"] == []
    listed = {store["id"] for store in alice["data"][0]["stores"]}
    assert listed == set(world.a.stores.values())
    assert not listed & set(world.b.stores.values())


@pytest.mark.parametrize("user", ["alice", "amy", "eve"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/v1/organizations/{org}", None),
        ("PATCH", "/v1/organizations/{org}", {"name": "Hijacked"}),
        ("GET", "/v1/organizations/{org}/stores", None),
        ("POST", "/v1/organizations/{org}/stores", {"name": "Evil", "slug": "evil"}),
    ],
)
async def test_other_organisation_routes_are_not_found_and_indistinguishable(
    client: AsyncClient,
    world: World,
    user: str,
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    foreign = await client.request(
        method, path.format(org=world.b.org_id), json=body, headers=as_user(user)
    )
    missing = await client.request(
        method, path.format(org=new_id()), json=body, headers=as_user(user)
    )

    assert foreign.status_code == 404
    same_failure(foreign, missing)
    assert world.b.org_id not in foreign.text
    org_name = await world.platform_value(
        "SELECT name FROM organizations WHERE id = :i", i=world.b.org_id
    )
    store_count = await world.platform_value(
        "SELECT count(*) FROM stores WHERE organization_id = :i", i=world.b.org_id
    )
    assert (org_name, store_count) == ("Org b", len(STORE_SLUGS))


# --- API: stores ----------------------------------------------------------------


@pytest.mark.parametrize("user", ["alice", "amy", "eve"])
@pytest.mark.parametrize("slug", STORE_SLUGS)
@pytest.mark.parametrize(
    ("method", "body"), [("GET", None), ("PATCH", {"name": "Hijacked"})]
)
async def test_other_organisations_store_is_not_found_and_indistinguishable(
    client: AsyncClient,
    world: World,
    user: str,
    slug: str,
    method: str,
    body: dict[str, str] | None,
) -> None:
    store_id = world.b.stores[slug]

    foreign = await client.request(
        method, f"/v1/stores/{store_id}", json=body, headers=as_user(user)
    )
    missing = await client.request(
        method, f"/v1/stores/{new_id()}", json=body, headers=as_user(user)
    )

    assert foreign.status_code == 404
    same_failure(foreign, missing)
    assert store_id not in foreign.text
    name = await world.platform_value(
        "SELECT name FROM stores WHERE id = :i", i=store_id
    )
    assert name == f"b {slug}"


async def test_owner_manages_every_own_store_but_never_a_foreign_one(
    client: AsyncClient, world: World
) -> None:
    for slug, store_id in world.a.stores.items():
        own = await client.patch(
            f"/v1/stores/{store_id}",
            json={"name": f"Renamed {slug}"},
            headers=as_user("alice"),
        )
        assert own.status_code == 200
        assert own.json()["data"]["id"] == store_id
    for store_id in world.b.stores.values():
        foreign = await client.patch(
            f"/v1/stores/{store_id}", json={"name": "Nope"}, headers=as_user("alice")
        )
        assert foreign.status_code == 404
    names = await world.platform_value(
        "SELECT string_agg(name, ',' ORDER BY slug) FROM stores "
        "WHERE organization_id = :o",
        o=world.b.org_id,
    )
    assert names == "b east,b north,b south"


@pytest.mark.parametrize("store_id", ["x" * 129, "%00", "' OR 1=1 --", "A" * 24, "*"])
async def test_malformed_and_guessed_store_ids_are_all_plain_not_found(
    client: AsyncClient, store_id: str
) -> None:
    reference = await client.get(f"/v1/stores/{new_id()}", headers=as_user("alice"))

    response = await client.get(f"/v1/stores/{store_id}", headers=as_user("alice"))

    assert response.status_code == 404
    same_failure(response, reference)


async def test_selected_store_claims_are_not_an_authorisation_boundary(
    client: AsyncClient, world: World
) -> None:
    own = world.a.stores["north"]
    target = world.b.stores["north"]
    claims = {
        "X-Store-Id": own,
        "X-Selected-Store": own,
        "X-Organization-Id": world.a.org_id,
        "Cookie": f"selected_store={own}; store_id={own}",
    }

    response = await client.get(
        f"/v1/stores/{target}?store_id={own}&organization_id={world.a.org_id}",
        headers={**as_user("alice"), **claims},
    )

    assert response.status_code == 404
    assert target not in response.text


async def test_role_in_one_organisation_grants_nothing_in_the_other(
    client: AsyncClient, world: World
) -> None:
    # carol is STAFF in A and OWNER in B: her B ownership must not widen her A rights.
    in_a = await client.patch(
        f"/v1/stores/{world.a.stores['east']}",
        json={"name": "Staff edit"},
        headers=as_user("carol"),
    )
    in_b = await client.patch(
        f"/v1/stores/{world.b.stores['east']}",
        json={"name": "Owner edit"},
        headers=as_user("carol"),
    )

    assert in_a.status_code == 403
    assert in_b.status_code == 200
    name_in_a = await world.platform_value(
        "SELECT name FROM stores WHERE id = :i", i=world.a.stores["east"]
    )
    assert name_in_a == "a east"


async def test_member_without_write_role_is_forbidden_in_own_org_and_blind_elsewhere(
    client: AsyncClient, world: World
) -> None:
    own_read = await client.get(
        f"/v1/stores/{world.a.stores['north']}", headers=as_user("amy")
    )
    own_write = await client.patch(
        f"/v1/stores/{world.a.stores['north']}",
        json={"name": "x"},
        headers=as_user("amy"),
    )
    foreign_write = await client.patch(
        f"/v1/stores/{world.b.stores['north']}",
        json={"name": "x"},
        headers=as_user("amy"),
    )

    assert own_read.status_code == 200
    assert own_write.status_code == 403
    assert foreign_write.status_code == 404


async def test_responses_never_carry_connection_details(
    client: AsyncClient, world: World
) -> None:
    north = world.a.stores["north"]
    await world.provision(north)
    envelope = str(
        await world.platform_value(
            "SELECT connection_string_encrypted FROM stores WHERE id = :i", i=north
        )
    )
    paths = [
        f"/v1/stores/{north}",
        f"/v1/organizations/{world.a.org_id}/stores",
        f"/v1/organizations/{world.a.org_id}",
        "/v1/organizations",
    ]

    for path in paths:
        response = await client.get(path, headers=as_user("alice"))
        assert response.status_code == 200
        for secret in (
            envelope,
            "postgresql",
            "connection_string",
            database_name_for(north),
        ):
            assert secret not in response.text, path


async def test_cross_organisation_store_create_adds_nothing(
    client: AsyncClient, world: World
) -> None:
    response = await client.post(
        f"/v1/organizations/{world.b.org_id}/stores",
        json={"name": "Intruder", "slug": "intruder"},
        headers=as_user("alice"),
    )

    assert response.status_code == 404
    count = await world.platform_value(
        "SELECT count(*) FROM stores WHERE slug = 'intruder'"
    )
    assert count == 0


# --- Data: separate databases ---------------------------------------------------


async def test_six_stores_are_six_distinct_databases(world: World) -> None:
    await world.provision_all()

    names = [
        await world.store_value(sid, "SELECT current_database()")
        for sid in world.every_store()
    ]

    assert names == [database_name_for(sid) for sid in world.every_store()]
    assert len(set(names)) == 6
    assert not set(names) & set(world.databases)


async def test_each_store_session_reads_only_its_own_rows(world: World) -> None:
    await world.provision_all()

    for store_id in world.every_store():
        assert await world.markers(store_id) == [store_id]


async def test_a_write_in_one_store_reaches_no_other_store(world: World) -> None:
    await world.provision_all()
    writer = world.a.stores["north"]

    async with open_store_session(writer, world.provider) as session:
        await session.execute(
            text("INSERT INTO marker (owner) VALUES ('secret-order')")
        )
        await session.execute(text("CREATE TABLE orders (id int)"))
        await session.commit()

    assert await world.markers(writer) == [writer, "secret-order"]
    assert await world.store_value(writer, "SELECT to_regclass('orders')") is not None
    for other in set(world.every_store()) - {writer}:
        assert await world.markers(other) == [other]
        assert await world.store_value(other, "SELECT to_regclass('orders')") is None


async def test_deleting_in_one_store_leaves_the_others_intact(world: World) -> None:
    await world.provision_all()
    victim = world.b.stores["east"]

    async with open_store_session(victim, world.provider) as session:
        await session.execute(text("DELETE FROM marker"))
        await session.commit()

    assert await world.markers(victim) == []
    for other in set(world.every_store()) - {victim}:
        assert await world.markers(other) == [other]


async def test_a_store_session_cannot_query_another_database_or_the_platform(
    world: World,
) -> None:
    await world.provision_all()
    mine = world.a.stores["north"]
    other_database = database_name_for(world.b.stores["north"])

    async with open_store_session(mine, world.provider) as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text(f'SELECT owner FROM "{other_database}".public.marker')
            )
    for platform_table in ("users", "stores", "memberships", "organizations"):
        found = await world.store_value(mine, f"SELECT to_regclass('{platform_table}')")
        assert found is None


async def test_the_platform_database_holds_no_store_data(world: World) -> None:
    await world.provision_all()

    found = await world.platform_value("SELECT to_regclass('marker')")

    assert found is None
    for store_id in world.every_store():
        database = await world.store_value(store_id, "SELECT current_database()")
        assert database not in world.databases


# --- Data: connection strings are bound to their store --------------------------


async def test_a_connection_string_cannot_be_decrypted_under_another_store_id(
    world: World,
) -> None:
    north = world.a.stores["north"]
    dsn = await world.provision(north)
    envelope = world.codec.encrypt(dsn, north)

    assert world.codec.decrypt(envelope, north) == dsn
    for other in set(world.every_store()) - {north}:
        with pytest.raises(StoreSecretUnavailable):
            world.codec.decrypt(envelope, other)
    replayed = Store(
        id=world.b.stores["north"],
        organization_id=world.b.org_id,
        name="n",
        slug="n",
        connection_string_encrypted=envelope,
    )
    with pytest.raises(StoreSecretUnavailable):
        store_secrets.reveal_connection_string(replayed, world.codec)


@pytest.mark.parametrize(
    ("victim", "donor"),
    [(("b", "north"), ("a", "north")), (("a", "south"), ("a", "east"))],
    ids=["across-organisations", "within-organisation"],
)
async def test_a_copied_connection_string_is_refused_and_the_donor_stays_untouched(
    world: World, victim: tuple[str, str], donor: tuple[str, str]
) -> None:
    await world.provision_all()
    tenants = {"a": world.a, "b": world.b}
    victim_id = tenants[victim[0]].stores[victim[1]]
    donor_id = tenants[donor[0]].stores[donor[1]]
    await world.copy_ciphertext(donor_id, victim_id)

    with pytest.raises(StoreDatabaseUnavailable) as caught:
        async with open_store_session(victim_id, world.provider) as session:
            await session.execute(text("DELETE FROM marker"))
            await session.commit()

    assert "postgresql" not in str(caught.value)
    assert await world.markers(donor_id) == [donor_id]
    assert await world.raw_markers(victim_id) == [victim_id]


async def test_an_unknown_store_id_opens_no_session(world: World) -> None:
    await world.provision_all()

    with pytest.raises(StoreNotFound):
        async with open_store_session(new_id(), world.provider):
            pass


# --- Data: the migration runner stays inside the database it was given ----------


def make_tree(tmp_path: Path) -> Path:
    real = Path(__file__).resolve().parents[2] / "alembic_store"
    tree = tmp_path / "alembic_store"
    (tree / "versions").mkdir(parents=True)
    for name in ("env.py", "script.py.mako"):
        (tree / name).write_text((real / name).read_text())
    baseline = real / "versions" / "0001_store_baseline.py"
    (tree / "versions" / baseline.name).write_text(baseline.read_text())
    (tree / "versions" / "0002_widgets.py").write_text(WIDGETS_REVISION)
    return tree


async def has_widgets(world: World, store_id: str) -> bool:
    found = await world.store_value(store_id, "SELECT to_regclass('widgets')")
    return found is not None


async def schema_version(world: World, store_id: str) -> object:
    return await world.platform_value(
        "SELECT schema_version FROM stores WHERE id = :i", i=store_id
    )


async def test_migrating_one_store_changes_no_other_database(
    world: World, tmp_path: Path
) -> None:
    await world.provision_all()
    target = world.a.stores["north"]

    version = await migrate_store(
        target, world.provider, script_location=make_tree(tmp_path)
    )

    assert version == 2
    assert await has_widgets(world, target)
    for other in set(world.every_store()) - {target}:
        assert not await has_widgets(world, other)
        assert await schema_version(world, other) == 0
        assert await world.markers(other) == [other]


async def test_migrate_active_stores_skips_other_statuses_and_keeps_data(
    world: World, tmp_path: Path
) -> None:
    await world.provision_all()
    suspended, provisioning = world.b.stores["south"], world.a.stores["east"]
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = 'SUSPENDED' WHERE id = :i"),
            {"i": suspended},
        )
        await connection.execute(
            text("UPDATE stores SET status = 'PROVISIONING' WHERE id = :i"),
            {"i": provisioning},
        )

    report = await migrate_active_stores(
        world.provider, script_location=make_tree(tmp_path)
    )

    assert report.succeeded
    skipped = {suspended, provisioning}
    assert {r.store_id for r in report.migrated} == set(world.every_store()) - skipped
    for store_id in world.every_store():
        assert await has_widgets(world, store_id) is (store_id not in skipped)
        assert await world.markers(store_id) == [store_id]


async def test_a_store_with_a_replayed_connection_string_fails_without_touching_donor(
    world: World, tmp_path: Path
) -> None:
    await world.provision_all()
    victim, donor = world.b.stores["east"], world.a.stores["east"]
    await world.copy_ciphertext(donor, victim)

    with pytest.raises(StoreMigrationFailed) as caught:
        await migrate_store(victim, world.provider, script_location=make_tree(tmp_path))

    assert caught.value.store_id == victim
    assert "postgresql" not in str(caught.value)
    assert not await has_widgets(world, donor)
    assert await schema_version(world, donor) == 0
