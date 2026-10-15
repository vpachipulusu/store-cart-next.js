"""Provision the database that backs one store (KAN-55, ADR-005).

``DatabaseProvisioner`` is the interface; ``LocalDatabaseProvisioner`` creates a database
on the Docker Postgres and ``NeonDatabaseProvisioner`` creates one through the Neon API.
``get_database_provisioner`` picks one from ``STORE_DB_PROVIDER``. Nothing here is wired
into store creation yet: a later ticket calls ``create_database`` and stores the result
with ``store_secrets.set_connection_string``.

Rules shared by both providers:

* The database name derives from the store id and is validated before use. Identifiers
  cannot be bound parameters, so the name is checked against a strict pattern and then
  quoted; values (for example in the existence check) are always bound.
* ``create_database`` is idempotent and returns the connection string. Treat it as a
  secret: it is never logged and never placed in an exception.
* Errors carry only the store id. The Neon API key never leaves the Authorization header.
* No provider creates an engine (ruff TID251). The local provider reuses the platform
  engine for its admin connection, which needs the CREATEDB privilege.
"""

import logging
import re
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings

logger = logging.getLogger("storecart.store_provisioning")

# Ids are 24 character cuid2 values; legacy ids are cuid (25 characters).
_STORE_ID_PATTERN = re.compile(r"^[a-z0-9]{8,40}$")
DATABASE_NAME_PREFIX = "store_"
NEON_API_BASE_URL = "https://console.neon.tech/api/v2"
REQUEST_TIMEOUT_SECONDS = 30.0


class ProvisioningError(Exception):
    """Provisioning failed. Never carries a connection string or an API key."""

    def __init__(self, store_id: str) -> None:
        super().__init__(f"{type(self).__name__}: store {store_id}")
        self.store_id = store_id


class InvalidStoreId(ProvisioningError):
    """The store id cannot be turned into a safe database name."""


class ProvisionerNotConfigured(ProvisioningError):
    """The selected provider is missing configuration (``missing`` names the variables)."""

    def __init__(self, provider: str, missing: tuple[str, ...]) -> None:
        Exception.__init__(
            self, f"{provider} provisioner is not configured: set {', '.join(missing)}"
        )
        self.store_id = ""
        self.provider = provider
        self.missing = missing


class ProvisioningFailed(ProvisioningError):
    """The provider rejected or could not complete the request."""


def database_name_for(store_id: str) -> str:
    """Database name for a store, or InvalidStoreId. Safe to quote as an identifier."""
    if not _STORE_ID_PATTERN.fullmatch(store_id):
        raise InvalidStoreId(store_id[:64])
    return f"{DATABASE_NAME_PREFIX}{store_id}"


class DatabaseProvisioner(Protocol):
    """Creates, finds and removes the database of one store."""

    async def create_database(self, store_id: str) -> str:
        """Ensure the store's database exists; return its connection string (secret)."""

    async def database_exists(self, store_id: str) -> bool:
        """Whether the store's database exists."""

    async def delete_database(self, store_id: str) -> None:
        """Drop the store's database; a no-op when it does not exist."""


class LocalDatabaseProvisioner:
    """Creates databases on the Postgres behind the platform engine (Docker, local)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def _quoted(self, name: str) -> str:
        return self._engine.dialect.identifier_preparer.quote_identifier(name)

    def _connection_string(self, name: str) -> str:
        return self._engine.url.set(database=name).render_as_string(hide_password=False)

    def _admin(self) -> AsyncEngine:
        return self._engine.execution_options(isolation_level="AUTOCOMMIT")

    async def _exists(self, name: str) -> bool:
        async with self._admin().connect() as connection:
            row = await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            )
            return row.first() is not None

    async def database_exists(self, store_id: str) -> bool:
        name = database_name_for(store_id)
        try:
            return await self._exists(name)
        except SQLAlchemyError:
            raise ProvisioningFailed(store_id) from None

    async def create_database(self, store_id: str) -> str:
        name = database_name_for(store_id)
        try:
            if not await self._exists(name):
                async with self._admin().connect() as connection:
                    await connection.execute(
                        text(f"CREATE DATABASE {self._quoted(name)}")
                    )
        except SQLAlchemyError:
            # A concurrent caller may have created it between the check and CREATE.
            try:
                if await self._exists(name):
                    return self._connection_string(name)
            except SQLAlchemyError:
                pass
            logger.error("local database creation failed", extra={"store_id": store_id})
            raise ProvisioningFailed(store_id) from None
        return self._connection_string(name)

    async def delete_database(self, store_id: str) -> None:
        name = database_name_for(store_id)
        try:
            async with self._admin().connect() as connection:
                await connection.execute(
                    text(f"DROP DATABASE IF EXISTS {self._quoted(name)} WITH (FORCE)")
                )
        except SQLAlchemyError:
            logger.error("local database deletion failed", extra={"store_id": store_id})
            raise ProvisioningFailed(store_id) from None


class NeonDatabaseProvisioner:
    """Creates databases on one Neon project branch through the Neon API v2.

    Endpoints used (``{base}`` defaults to https://console.neon.tech/api/v2):

    * ``GET    {base}/projects/{project}/branches/{branch}/databases``
    * ``POST   {base}/projects/{project}/branches/{branch}/databases``
    * ``DELETE {base}/projects/{project}/branches/{branch}/databases/{name}``
    * ``GET    {base}/projects/{project}/connection_uri`` (pooled)
    """

    def __init__(
        self,
        api_key: str,
        project_id: str,
        branch_id: str,
        role_name: str,
        *,
        base_url: str = NEON_API_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._project = quote(project_id, safe="")
        self._branch = quote(branch_id, safe="")
        self._role = role_name
        self._base = base_url.rstrip("/")
        self._client = client

    @property
    def _databases_path(self) -> str:
        return f"/projects/{self._project}/branches/{self._branch}/databases"

    async def _send(
        self, client: httpx.AsyncClient, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        return await client.request(
            method,
            f"{self._base}{path}",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )

    async def _request(
        self, store_id: str, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        try:
            if self._client is not None:
                return await self._send(self._client, method, path, **kwargs)
            async with httpx.AsyncClient() as client:
                return await self._send(client, method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.error(
                "neon request failed: %s",
                type(exc).__name__,
                extra={"store_id": store_id},
            )
            raise ProvisioningFailed(store_id) from None

    def _fail(self, store_id: str, response: httpx.Response) -> ProvisioningFailed:
        logger.error(
            "neon request rejected: status=%s",
            response.status_code,
            extra={"store_id": store_id},
        )
        return ProvisioningFailed(store_id)

    async def _exists(self, store_id: str, name: str) -> bool:
        response = await self._request(store_id, "GET", self._databases_path)
        if response.status_code != 200:
            raise self._fail(store_id, response)
        try:
            databases = response.json()["databases"]
            return any(item["name"] == name for item in databases)
        except (ValueError, KeyError, TypeError):
            raise ProvisioningFailed(store_id) from None

    async def database_exists(self, store_id: str) -> bool:
        return await self._exists(store_id, database_name_for(store_id))

    async def _connection_uri(self, store_id: str, name: str) -> str:
        response = await self._request(
            store_id,
            "GET",
            f"/projects/{self._project}/connection_uri",
            params={
                "branch_id": self._branch,
                "database_name": name,
                "role_name": self._role,
                "pooled": "true",
            },
        )
        if response.status_code != 200:
            raise self._fail(store_id, response)
        try:
            uri = response.json()["uri"]
        except (ValueError, KeyError, TypeError):
            raise ProvisioningFailed(store_id) from None
        if not isinstance(uri, str) or not uri:
            raise ProvisioningFailed(store_id)
        return uri

    async def create_database(self, store_id: str) -> str:
        name = database_name_for(store_id)
        if not await self._exists(store_id, name):
            response = await self._request(
                store_id,
                "POST",
                self._databases_path,
                json={"database": {"name": name, "owner_name": self._role}},
            )
            # 409: created concurrently, which is the state we want.
            if response.status_code not in (200, 201, 409):
                raise self._fail(store_id, response)
        return await self._connection_uri(store_id, name)

    async def delete_database(self, store_id: str) -> None:
        name = database_name_for(store_id)
        response = await self._request(
            store_id, "DELETE", f"{self._databases_path}/{quote(name, safe='')}"
        )
        if response.status_code not in (200, 202, 404):
            raise self._fail(store_id, response)


def get_database_provisioner(
    settings: Settings, engine: AsyncEngine | None = None
) -> DatabaseProvisioner:
    """Provisioner chosen by ``settings.STORE_DB_PROVIDER`` ("local" or "neon").

    Raises ProvisionerNotConfigured when "neon" is selected without its variables.
    ``engine`` defaults to the platform engine (imported lazily).
    """
    provider = settings.STORE_DB_PROVIDER.strip().lower()
    if provider == "local":
        if engine is None:
            from app.core.database import engine as platform_engine

            engine = platform_engine
        return LocalDatabaseProvisioner(engine)
    if provider == "neon":
        api_key = (
            settings.NEON_API_KEY.get_secret_value() if settings.NEON_API_KEY else ""
        )
        values = {
            "NEON_API_KEY": api_key,
            "NEON_PROJECT_ID": settings.NEON_PROJECT_ID or "",
            "NEON_BRANCH_ID": settings.NEON_BRANCH_ID or "",
            "NEON_ROLE_NAME": settings.NEON_ROLE_NAME or "",
        }
        missing = tuple(name for name, value in values.items() if not value)
        if missing:
            raise ProvisionerNotConfigured("neon", missing)
        return NeonDatabaseProvisioner(
            api_key,
            values["NEON_PROJECT_ID"],
            values["NEON_BRANCH_ID"],
            values["NEON_ROLE_NAME"],
            base_url=settings.NEON_API_BASE_URL,
        )
    raise ProvisionerNotConfigured(provider, ("STORE_DB_PROVIDER=local|neon",))
