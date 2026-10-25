"""Fakes for the store database provisioners (KAN-55): a Neon API and an AsyncEngine.

KAN-238: the fake engine also understands the store role SQL from ``store_roles``
(roles, their passwords, database owners and the PUBLIC revoke), and the fake Neon
provisioner runs that SQL on a fake admin connection.
"""

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, Self, cast

import httpx
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.store_provisioning import AdminConnection, NeonDatabaseProvisioner

API_KEY = "neon-secret-api-key-123"
NEON_URI = "postgresql://owner:hunter2@ep-x-pooler.neon.tech/store_x?sslmode=require"
NEON_DIRECT_URI = "postgresql://owner:hunter2@ep-x.neon.tech/store_x?sslmode=require"
NEON_BASE = "https://neon.test/api/v2"
DB_PATH = "/api/v2/projects/proj-1/branches/br-1/databases"
URI_PATH = "/api/v2/projects/proj-1/connection_uri"


class FakeNeon:
    """In-memory Neon API behind httpx.MockTransport."""

    def __init__(self, existing: tuple[str, ...] = (), post_status: int = 201) -> None:
        self.databases = list(existing)
        self.post_status = post_status
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == DB_PATH:
            return httpx.Response(
                200, json={"databases": [{"name": name} for name in self.databases]}
            )
        if request.method == "POST" and path == DB_PATH:
            if self.post_status in (200, 201):
                self.databases.append(json.loads(request.content)["database"]["name"])
            return httpx.Response(self.post_status, json={})
        if request.method == "DELETE" and path.startswith(f"{DB_PATH}/"):
            name = path.rsplit("/", 1)[1]
            if name not in self.databases:
                return httpx.Response(404, json={})
            self.databases.remove(name)
            return httpx.Response(200, json={})
        if request.method == "GET" and path == URI_PATH:
            pooled = request.url.params["pooled"] == "true"
            uri = NEON_URI if pooled else NEON_DIRECT_URI
            database = request.url.params["database_name"]
            return httpx.Response(200, json={"uri": uri.replace("store_x", database)})
        return httpx.Response(500, json={})

    def provisioner(
        self, engine: "FakeEngine | None" = None
    ) -> NeonDatabaseProvisioner:
        return neon_with(self.handle, engine)


def neon_with(
    handler: Any, engine: "FakeEngine | None" = None
) -> NeonDatabaseProvisioner:
    """A Neon provisioner on a mocked API; its admin SQL runs on ``engine`` (a fake)."""
    return NeonDatabaseProvisioner(
        API_KEY,
        "proj-1",
        "br-1",
        "owner",
        base_url=NEON_BASE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        admin_connection=fake_admin_connection(engine or FakeEngine()),
    )


def fake_admin_connection(engine: "FakeEngine") -> AdminConnection:
    """Stands in for ``store_sessions.open_admin_connection``; records each URI."""

    @asynccontextmanager
    async def admin_connection(uri: str) -> AsyncIterator[Any]:
        engine.admin_uris.append(uri)
        async with engine.begin() as connection:
            yield connection

    return cast(AdminConnection, admin_connection)


_ROLE = re.compile(r'^(CREATE|ALTER) ROLE "([^"]+)" WITH LOGIN PASSWORD \'([^\']+)\'$')
_OWNER = re.compile(r'^ALTER DATABASE "([^"]+)" OWNER TO "([^"]+)"$')


class FakeResult:
    def __init__(self, found: bool) -> None:
        self._found = found

    def first(self) -> tuple[int] | None:
        return (1,) if self._found else None


class FakeConnection:
    def __init__(self, engine: "FakeEngine") -> None:
        self._engine = engine

    async def __aenter__(self) -> Self:
        self._engine.fail_connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def execute(
        self, statement: Any, params: dict[str, Any] | None = None
    ) -> Any:
        sql = str(statement)
        self._engine.statements.append(sql)
        if sql.startswith("SELECT 1 FROM pg_database"):
            self._engine.fail_if("select")
            assert params is not None
            return FakeResult(params["name"] in self._engine.databases)
        if sql.startswith("CREATE DATABASE "):
            name = sql.removeprefix("CREATE DATABASE ").strip('"')
            if self._engine.race_on_create:
                self._engine.databases.add(name)  # created by someone else
            self._engine.fail_if("create")
            self._engine.databases.add(name)
            return None
        if sql.startswith("DROP DATABASE IF EXISTS "):
            self._engine.fail_if("drop")
            name = sql.removeprefix("DROP DATABASE IF EXISTS ").split(" ")[0]
            self._engine.databases.discard(name.strip('"'))
            return None
        raise AssertionError(f"unexpected statement: {sql}")

    async def scalar(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(statement)
        self._engine.statements.append(sql)
        if sql.startswith("SELECT 1 FROM pg_roles"):
            assert params is not None
            return 1 if params["role"] in self._engine.roles else None
        raise AssertionError(f"unexpected scalar: {sql}")

    async def exec_driver_sql(self, sql: str) -> None:
        engine = self._engine
        if role := _ROLE.match(sql):
            engine.fail_if("role")
            verb, name, password = role.groups()
            assert (verb == "ALTER") == (name in engine.roles), sql
            engine.roles[name] = password
            engine.statements.append(f"{verb} ROLE {name} PASSWORD <redacted>")
            return
        engine.statements.append(sql)
        if owner := _OWNER.match(sql):
            database, name = owner.groups()
            assert name in engine.roles
            engine.owners[database] = name
        elif sql.startswith("DROP ROLE IF EXISTS "):
            engine.fail_if("drop_role")
            engine.roles.pop(sql.removeprefix("DROP ROLE IF EXISTS ").strip('"'), None)
        elif sql.startswith("DROP ROLE "):
            engine.roles.pop(sql.removeprefix("DROP ROLE ").strip('"'))
        elif sql.startswith(("GRANT ", "REVOKE ", "REASSIGN OWNED ", "DROP OWNED ")):
            return
        else:
            raise AssertionError(f"unexpected statement: {sql}")


class FakeEngine:
    """Just enough of AsyncEngine for LocalDatabaseProvisioner; records statements."""

    def __init__(self, databases: tuple[str, ...] = ()) -> None:
        self.databases = set(databases)
        self.statements: list[str] = []
        self.fail: set[str] = set()
        self.race_on_create = False
        self.connect_error: BaseException | None = None
        self.dialect = asyncpg.dialect()
        self.url = make_url("postgresql+asyncpg://admin:s3cret@db.local:5432/platform")
        self.isolation_levels: list[str] = []
        self.roles: dict[str, str] = {}  # role name -> current password
        self.owners: dict[str, str] = {}  # database -> owning role
        self.admin_uris: list[str] = []

    def fail_if(self, operation: str) -> None:
        if operation in self.fail:
            raise OperationalError("stmt", {}, Exception("boom s3cret"))

    def fail_connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error

    def execution_options(self, **options: Any) -> "FakeEngine":
        self.isolation_levels.append(options["isolation_level"])
        return self

    def connect(self) -> FakeConnection:
        return FakeConnection(self)

    def begin(self) -> FakeConnection:
        """A transaction: the fake does not roll back, which no test relies on."""
        return FakeConnection(self)

    def as_engine(self) -> AsyncEngine:
        return cast(AsyncEngine, self)
