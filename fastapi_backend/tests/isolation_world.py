"""The world the tenant isolation suites run in (KAN-58, KAN-195).

Two organisations with three stores each, every store on its own real Postgres database
(created by the local provisioner, connection string encrypted with the store id as AAD,
reached only through ``open_store_session``), plus a handful of users:

=======  =====================================  =====================
user     role                                   firebase uid
=======  =====================================  =====================
alice    OWNER of A                             ``fb-alice``
dana     ADMIN of A                             ``fb-dana``
amy      STAFF of A                             ``fb-amy``
bob      OWNER of B                             ``fb-bob``
gus      ADMIN of B                             ``fb-gus``
carol    STAFF of A and OWNER of B              ``fb-carol``
eve      no organisation                        ``fb-eve``
root     platform admin when a test grants it   ``fb-root``
=======  =====================================  =====================

Limits of what this proves (read before trusting a green run):

* Isolation of store data is proven at the **database** level (separate databases and
  encrypted, store-bound connection strings), not at the **role** level: every store
  database is created by the one server role the test uses, so a store session that was
  handed another store's DSN would connect. The suite proves that cannot happen through
  the registry, not that Postgres would stop it.
* The "cannot query another database" check matches Postgres's own wording
  (``cross-database references are not implemented``); a different server version may
  word it differently and the match would need updating.
* The platform database is built from the models (``create_all``), not from the Alembic
  chain; migration drift is covered by the other e2e suites.
"""

import json
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Any

import pytest
from fastapi import FastAPI, Header, HTTPException
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import app.models.platform  # noqa: F401  (registers every table on Base.metadata)
from app.api.auth import get_session_identity
from app.api.deps import get_rate_limiter, get_session_provider
from app.core.config import settings
from app.core.database import DefaultSessionProvider
from app.core.firebase import AuthenticationFailed, VerifiedIdentity
from app.core.ids import new_id
from app.core.rate_limit import DisabledRateLimiter
from app.core.store_crypto import StoreSecretCodec, generate_key
from app.main import create_app
from app.models.platform.store import Store
from app.services import store_secrets
from app.services.store_provisioning import (
    LocalDatabaseProvisioner,
    database_name_for,
)
from app.services.store_sessions import open_store_session
from tests.pg_scaffold import (
    create_platform_database,
    drop_databases,
    require_local_test_server,
    sweep_stale_databases,
    unique_name,
    url_for,
)

DATABASE_PREFIX = "ks58"
STORE_SLUGS = ("north", "south", "east")
USERS = ("alice", "dana", "amy", "bob", "gus", "carol", "eve", "root")
MEMBERSHIPS = (
    ("alice", "a", "OWNER"),
    ("dana", "a", "ADMIN"),
    ("amy", "a", "STAFF"),
    ("bob", "b", "OWNER"),
    ("gus", "b", "ADMIN"),
    ("carol", "a", "STAFF"),
    ("carol", "b", "OWNER"),
)

COPY_CIPHERTEXT = (
    "UPDATE stores SET connection_string_encrypted = "
    "(SELECT connection_string_encrypted FROM stores WHERE id = :donor) "
    "WHERE id = :victim"
)


def internal_key() -> str:
    """The service key the app under test accepts (set for the whole suite by conftest)."""
    assert settings.BACKEND_INTERNAL_KEY is not None
    return settings.BACKEND_INTERNAL_KEY.get_secret_value()


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
        self.user_ids: dict[str, str] = {}

    def tenant(self, label: str) -> Tenant:
        return {"a": self.a, "b": self.b}[label]

    def every_store(self) -> list[str]:
        return [sid for tenant in (self.a, self.b) for sid in tenant.stores.values()]

    async def seed(self) -> None:
        self.user_ids = {name: new_id() for name in USERS}
        async with self.platform.begin() as connection:
            for name, user_id in self.user_ids.items():
                await connection.execute(
                    text(
                        "INSERT INTO users (id, firebase_uid, email, email_verified) "
                        "VALUES (:id, :uid, :email, true)"
                    ),
                    {"id": user_id, "uid": f"fb-{name}", "email": f"{name}@x.test"},
                )
            for label in ("a", "b"):
                tenant = self.tenant(label)
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
            for name, label, role in MEMBERSHIPS:
                await connection.execute(
                    text(
                        "INSERT INTO memberships (id, organization_id, user_id, role) "
                        "VALUES (:id, :o, :u, :r)"
                    ),
                    {
                        "id": new_id(),
                        "o": self.tenant(label).org_id,
                        "u": self.user_ids[name],
                        "r": role,
                    },
                )

    async def grant_platform_admin(self, name: str, permissions: list[str]) -> None:
        """Make an existing user a platform admin holding ``permissions``."""
        async with self.platform.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO admin_users (id, user_id, role, permissions) "
                    "VALUES (:id, :u, 'admin', CAST(:p AS jsonb))"
                ),
                {
                    "id": new_id(),
                    "u": self.user_ids[name],
                    "p": json.dumps(permissions),
                },
            )

    async def remove_membership(self, name: str, label: str) -> None:
        async with self.platform.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM memberships WHERE user_id = :u AND organization_id = :o"
                ),
                {"u": self.user_ids[name], "o": self.tenant(label).org_id},
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
            rows = await session.execute(
                text("SELECT owner FROM marker ORDER BY owner")
            )
            return [row[0] for row in rows]

    async def platform_value(self, sql: str, **params: str) -> Any:
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

    async def store_value(self, store_id: str, sql: str) -> Any:
        async with open_store_session(store_id, self.provider) as session:
            return (await session.execute(text(sql))).scalar_one()

    async def copy_ciphertext(self, donor: str, victim: str) -> None:
        async with self.platform.begin() as connection:
            await connection.execute(
                text(COPY_CIPHERTEXT), {"donor": donor, "victim": victim}
            )

    async def snapshot(self) -> dict[str, list[tuple[Any, ...]]]:
        """Every platform row an attacker could change, to prove a probe changed nothing."""
        queries = {
            "organizations": "SELECT id, name, slug, subscription_tier, subscription_status, "
            "stripe_customer_id, stripe_subscription_id, stripe_price_id "
            "FROM organizations ORDER BY id",
            "stores": "SELECT id, name, slug, status, connection_string_encrypted "
            "FROM stores ORDER BY id",
            "memberships": "SELECT organization_id, user_id, role FROM memberships "
            "ORDER BY organization_id, user_id",
            "users": "SELECT id, email, display_name FROM users ORDER BY id",
            "admin_users": "SELECT user_id, role FROM admin_users ORDER BY user_id",
            "audit_logs": "SELECT count(*) FROM audit_logs",
        }
        out: dict[str, list[tuple[Any, ...]]] = {}
        async with self.platform.connect() as connection:
            for key, sql in queries.items():
                out[key] = [tuple(row) for row in await connection.execute(text(sql))]
        return out


@asynccontextmanager
async def open_world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    """Build a world on the local test server and tear it down, whatever happens.

    Each teardown step runs in its own try (via ``AsyncExitStack``), so a failing drop
    of one database never leaves the others behind. Stale ``ks58_*`` databases from a
    killed run are swept first (platform databases only: a killed run can still leave its
    ``store_<id>`` databases behind; drop them by hand).
    """
    server = create_async_engine(require_local_test_server())
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(server.dispose)
        await sweep_stale_databases(server, DATABASE_PREFIX)
        platform_name = unique_name(DATABASE_PREFIX, "plat")
        names = [platform_name]
        cleanup.push_async_callback(lambda: drop_databases(server, names))
        platform = await create_platform_database(server, platform_name)
        cleanup.push_async_callback(platform.dispose)
        built = World(server, platform, names)

        async def delete_store_databases() -> None:
            # One call: drop_databases keeps going past a failing drop and raises at the end.
            await drop_databases(
                server, [database_name_for(sid) for sid in built.provisioned]
            )
            # KAN-238: each provisioned store also has its own role.
            for sid in built.provisioned:
                await built.provisioner.delete_database(sid)

        cleanup.push_async_callback(delete_store_databases)
        monkeypatch.setattr(store_secrets, "get_codec", lambda: built.codec)
        await built.seed()
        yield built


def as_user(name: str) -> dict[str, str]:
    return {"X-Test-Uid": f"fb-{name}"}


def session_for(name: str) -> dict[str, str]:
    """Headers for the real auth chain: the opaque session token of ``name``."""
    return {"X-Session-Token": f"session-{name}"}


class FakeFirebase:
    """Stands in for ``FirebaseIdentityProvider`` under the real auth chain.

    Only the Firebase network calls are replaced: the token is looked up here, then the
    production ``AuthService``, ``get_session_identity``, ``get_current_identity`` and the
    membership checks run unchanged. A uid in ``disabled`` is a banned (or revoked)
    account, which Firebase's ``check_revoked`` rejects as an invalid session.
    """

    def __init__(self) -> None:
        self.disabled: set[str] = set()
        self.calls: list[tuple[str, str]] = []

    def provider_class(self) -> type:
        outer = self

        class Provider:
            async def verify_session_cookie(self, token: str) -> Mapping[str, Any]:
                outer.calls.append(("verify", token))
                name = token.removeprefix("session-")
                uid = f"fb-{name}"
                if not token.startswith("session-") or uid in outer.disabled:
                    raise AuthenticationFailed()
                return {
                    "uid": uid,
                    "email": f"{name}@x.test",
                    "email_verified": True,
                    "auth_time": int(time.time()),
                }

            async def set_user_disabled(self, uid: str, disabled: bool) -> None:
                (outer.disabled.add if disabled else outer.disabled.discard)(uid)

            async def revoke_refresh_tokens(self, uid: str) -> None:
                outer.calls.append(("revoke", uid))

            async def delete_user(self, uid: str) -> None:
                outer.calls.append(("delete", uid))

        return Provider


def header_identity_app(world: World) -> FastAPI:
    """The real app with the session identity read from ``X-Test-Uid`` (no cookie)."""
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
    return app


def make_client(app: FastAPI) -> AsyncClient:
    """A client for ``app`` with the rate limiter off, so a real Upstash is never needed."""
    app.dependency_overrides[get_rate_limiter] = DisabledRateLimiter
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": internal_key()},
    )


def same_failure(response: Response, reference: Response) -> None:
    """Both responses are indistinguishable: status, body and cache header."""
    assert response.status_code == reference.status_code
    assert response.json() == reference.json()
    assert response.headers.get("cache-control") == reference.headers.get(
        "cache-control"
    )
