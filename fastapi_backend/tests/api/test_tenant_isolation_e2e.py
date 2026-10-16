"""Tenant isolation suite, part 1 (KAN-58, ADR-005): writes, store data and migrations.

Two organisations with three stores each, every store on its own real Postgres database
(see ``tests/isolation_world.py`` for the world, the users and the limits of what is
proven). This module holds the tests that change the world or provision store databases,
so each gets a fresh one:

* API: owners can manage their own stores but never a foreign one; a role in one
  organisation grants nothing in the other.
* Data: rows written through one store session never appear in any other store database
  (other organisation or sibling store), a connection string cannot be replayed under
  another store id, and the migration runner stays inside the database it was told to.

The read-only API probes (foreign ids answer exactly like missing ones) are in
``test_tenant_isolation_probes_e2e.py`` and share one world; roles, the real auth chain
and removed or banned users are in ``test_tenant_isolation_roles_e2e.py``.

Runs only when ``TEST_DATABASE_URL`` points at a throwaway local server whose database
name ends in ``_test``. It builds its own platform database (tables from the models) and
store databases, and drops them afterwards; the shared test database is not touched.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.ids import new_id
from app.core.store_crypto import StoreSecretUnavailable
from app.models.platform.store import Store
from app.services import store_secrets
from app.services.store_migrations import (
    StoreMigrationFailed,
    migrate_active_stores,
    migrate_store,
)
from app.services.store_provisioning import database_name_for
from app.services.store_sessions import (
    StoreDatabaseNotConfigured,
    StoreDatabaseUnavailable,
    StoreNotFound,
    open_store_session,
)
from tests.isolation_world import (
    World,
    as_user,
    header_identity_app,
    make_client,
    open_world,
    same_failure,
)
from tests.pg_scaffold import TEST_DATABASE_URL

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


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    async with open_world(monkeypatch) as built:
        yield built


@pytest.fixture
async def client(world: World) -> AsyncIterator[AsyncClient]:
    async with make_client(header_identity_app(world)) as http:
        yield http


# --- API: organisations ---------------------------------------------------------


# --- API: stores ----------------------------------------------------------------


async def test_owner_controls_prove_the_foreign_404s_are_not_routing_artifacts(
    client: AsyncClient, world: World
) -> None:
    org = world.a.org_id
    patch_org = await client.patch(
        f"/v1/organizations/{org}", json={"name": "Renamed"}, headers=as_user("alice")
    )
    staff_patch = await client.patch(
        f"/v1/organizations/{org}", json={"name": "Staff"}, headers=as_user("amy")
    )

    assert patch_org.status_code == 200
    assert staff_patch.status_code == 403
    assert (
        staff_patch.json()
        != (
            await client.get(f"/v1/organizations/{new_id()}", headers=as_user("amy"))
        ).json()
    )


@pytest.mark.parametrize("status", ["SUSPENDED", "PROVISIONING", "ARCHIVED"])
async def test_foreign_store_in_any_status_is_still_plain_not_found(
    client: AsyncClient, world: World, status: str
) -> None:
    store_id = world.b.stores["north"]
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET status = :s WHERE id = :i"),
            {"s": status, "i": store_id},
        )
    missing = await client.patch(
        f"/v1/stores/{new_id()}", json={"name": "x"}, headers=as_user("alice")
    )

    foreign = await client.patch(
        f"/v1/stores/{store_id}", json={"name": "x"}, headers=as_user("alice")
    )

    same_failure(foreign, missing)
    assert "not active" not in foreign.text


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

    assert await world.markers(writer) == sorted([writer, "secret-order"])
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
        # Postgres's own wording, see the limits in tests/isolation_world.py.
        with pytest.raises(DBAPIError, match="cross-database"):
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


async def test_tampered_or_missing_connection_strings_open_no_session(
    world: World,
) -> None:
    await world.provision_all()
    tampered, unset = world.a.stores["north"], world.b.stores["north"]
    envelope = str(
        await world.platform_value(
            "SELECT connection_string_encrypted FROM stores WHERE id = :i", i=tampered
        )
    )
    # Flip a character well inside the base64 payload: the last one can be padding
    # bits that decode to the same bytes, which would leave the envelope valid.
    flipped = envelope[:-10] + ("A" if envelope[-10] != "A" else "B") + envelope[-9:]
    async with world.platform.begin() as connection:
        await connection.execute(
            text("UPDATE stores SET connection_string_encrypted = :v WHERE id = :i"),
            {"v": flipped, "i": tampered},
        )
        await connection.execute(
            text("UPDATE stores SET connection_string_encrypted = NULL WHERE id = :i"),
            {"i": unset},
        )

    with pytest.raises(StoreDatabaseUnavailable):
        async with open_store_session(tampered, world.provider):
            pass
    with pytest.raises(StoreDatabaseNotConfigured):
        async with open_store_session(unset, world.provider):
            pass
    assert await world.raw_markers(tampered) == [tampered]


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
        (tree / name).write_text(
            (real / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    baseline = real / "versions" / "0001_store_baseline.py"
    (tree / "versions" / baseline.name).write_text(
        baseline.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tree / "versions" / "0002_widgets.py").write_text(
        WIDGETS_REVISION, encoding="utf-8"
    )
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
    assert {k.value: v for k, v in report.skipped.items()} == {
        "SUSPENDED": 1,
        "PROVISIONING": 1,
    }
    skipped = {suspended, provisioning}
    assert {r.store_id for r in report.migrated} == set(world.every_store()) - skipped
    for store_id in world.every_store():
        assert await has_widgets(world, store_id) is (store_id not in skipped)
        assert await world.markers(store_id) == [store_id]
    for store_id in skipped:
        assert await schema_version(world, store_id) == 0


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
