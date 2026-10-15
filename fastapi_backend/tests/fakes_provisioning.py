"""Fakes for the store database provisioners (KAN-55): a Neon API and an AsyncEngine."""

import json
from types import TracebackType
from typing import Any, Self, cast

import httpx
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.store_provisioning import NeonDatabaseProvisioner

API_KEY = "neon-secret-api-key-123"
NEON_URI = "postgresql://owner:hunter2@ep-x-pooler.neon.tech/store_x?sslmode=require"
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
            return httpx.Response(200, json={"uri": NEON_URI})
        return httpx.Response(500, json={})

    def provisioner(self) -> NeonDatabaseProvisioner:
        return neon_with(self.handle)


def neon_with(handler: Any) -> NeonDatabaseProvisioner:
    return NeonDatabaseProvisioner(
        API_KEY,
        "proj-1",
        "br-1",
        "owner",
        base_url=NEON_BASE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


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

    def as_engine(self) -> AsyncEngine:
        return cast(AsyncEngine, self)
