# Backend store database provisioning (KAN-55)

Each store has its own database (ADR-005). `app.services.store_provisioning` creates it. It is **not wired into store
creation or onboarding yet**; a later ticket calls `create_database(store_id)` and saves the result with
`store_secrets.set_connection_string` (KAN-53).

## Interface

```python
provisioner = get_database_provisioner(settings)       # chosen by STORE_DB_PROVIDER
connection_string = await provisioner.create_database(store_id)   # idempotent, returns a secret
await provisioner.database_exists(store_id)
await provisioner.delete_database(store_id)            # no-op when absent (cleanup)
```

Both providers implement the `DatabaseProvisioner` protocol. The database is named `store_<store id>`. The id must match
`^[a-z0-9]{8,40}$` (cuid and cuid2 ids do), otherwise `InvalidStoreId` is raised before anything reaches the database or
the API. Identifiers cannot be bound parameters, so the validated name is also quoted; values are always bound.

Errors derive from `ProvisioningError` and carry only the store id: `InvalidStoreId`, `ProvisioningFailed`,
`ProvisionerNotConfigured` (lists the missing variable names, never values). Connection strings and the Neon API key are
never logged or placed in an exception; underlying driver and HTTP errors are dropped (`from None`).

## Configuration

| Variable            | Purpose                                                                                              |
| ------------------- | ---------------------------------------------------------------------------------------------------- |
| `STORE_DB_PROVIDER` | `local` (default) or `neon`. Optional; local needs nothing else.                                     |
| `NEON_API_KEY`      | Neon API key (secret). Required only when `neon` is selected.                                        |
| `NEON_PROJECT_ID`   | Neon project that holds store databases. Required for `neon`.                                        |
| `NEON_BRANCH_ID`    | Branch (for example `br-...`) the databases are created on. Required for `neon`.                     |
| `NEON_ROLE_NAME`    | Role that owns the new databases and appears in the returned connection string. Required for `neon`. |
| `NEON_API_BASE_URL` | Optional. Defaults to `https://console.neon.tech/api/v2`.                                            |

Settings stay optional at startup. Selecting `neon` without the required variables fails when the provisioner is built
(`ProvisionerNotConfigured`), not at import.

## Local provider

`LocalDatabaseProvisioner` reuses the **platform engine** (`app.core.database.engine`) for an `AUTOCOMMIT` admin
connection, because ruff `TID251` forbids creating engines outside `database.py` and `store_sessions.py`. It runs
`CREATE DATABASE "store_<id>"` after checking `pg_database`, and `DROP DATABASE IF EXISTS ... WITH (FORCE)` on delete
(Postgres 13+). The `DATABASE_URL` role therefore needs `CREATEDB` (the Docker superuser has it). The returned string is
the platform URL with the database swapped, so it reuses the same host and credentials; it carries no `sslmode`.

## Neon provider

`NeonDatabaseProvisioner` calls the Neon API v2 over httpx with `Authorization: Bearer $NEON_API_KEY` (30 s timeout):

| Step                 | Request                                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| exists / idempotency | `GET /projects/{NEON_PROJECT_ID}/branches/{NEON_BRANCH_ID}/databases`                                                     |
| create               | `POST` the same path, body `{"database": {"name": "store_<id>", "owner_name": NEON_ROLE_NAME}}`; `409` counts as created |
| connection string    | `GET /projects/{NEON_PROJECT_ID}/connection_uri?branch_id=&database_name=&role_name=&pooled=true`, field `uri`            |
| delete               | `DELETE /projects/{NEON_PROJECT_ID}/branches/{NEON_BRANCH_ID}/databases/store_<id>`; `404` is fine                       |

The pooled URI matches the session factory, which turns off asyncpg's statement cache for PgBouncer (KAN-54). Neon runs
these changes as asynchronous operations; a locked branch answers with an error that surfaces as `ProvisioningFailed`, and
the caller may retry because `create_database` is idempotent. Tests use `httpx.MockTransport`; the real API is not called.

## Tests

- `tests/services/test_store_provisioning.py`: name validation and injection attempts, Neon create/exists/delete/
  idempotency/conflict/error paths with a mocked HTTP layer, no secrets in errors or logs, factory selection.
- `tests/services/test_store_provisioning_e2e.py`: the local provider on a real Postgres. Needs `TEST_DATABASE_URL`
  (database name ending `_test`, role with `CREATEDB`); skipped otherwise, and CI does not run it.

```bash
docker run -d --name kan55-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=kan55_test -p 55455:5432 postgres:17
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55455/kan55_test uv run pytest tests/services/test_store_provisioning_e2e.py
docker rm -f kan55-pg
```
