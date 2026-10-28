# Backend store database provisioning (KAN-55, KAN-238)

Each store has its own database and its own Postgres role (ADR-005). `app.services.store_provisioning` creates them;
the provisioning job (`store_provisioning_job`, KAN-56) calls `create_database(store_id)` and saves the result with
`store_secrets.set_connection_string` (KAN-53).

## Interface

```python
provisioner = get_database_provisioner(settings)       # chosen by STORE_DB_PROVIDER
connection_string = await provisioner.create_database(store_id)   # idempotent, rotates, returns a secret
await provisioner.database_exists(store_id)
await provisioner.delete_database(store_id)            # drops database and role; no-op when absent
```

## One role per store (KAN-238)

The database and its login role are both named `store_<store id>`. `app.services.store_roles.apply_store_role` runs, as
the provisioning role, connected to the store database, in one transaction that first pins
`search_path = pg_catalog, pg_temp` (so nothing a store role planted in `public` can run as the provisioning role;
the SQL is also schema-qualified), sets `lock_timeout` 10 s and takes the store's migration advisory lock (the key
`store_migrations` uses):

```sql
CREATE ROLE "store_<id>" WITH LOGIN CONNECTION LIMIT -1 VALID UNTIL 'infinity' PASSWORD '<generated>';  -- ALTER on a re-run
ALTER ROLE "store_<id>" RESET ALL;  ALTER ROLE "store_<id>" IN DATABASE "store_<id>" RESET ALL;
-- check: no privileged attribute, member of no role, no member but the provisioning role
GRANT "store_<id>" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE;  -- Postgres 16+
REVOKE CONNECT, TEMPORARY ON DATABASE "store_<id>" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE "store_<id>" TO "store_<id>";
GRANT USAGE, CREATE ON SCHEMA public TO "store_<id>";
-- then ALTER ... OWNER TO "store_<id>" for anything the provisioning role owns here (nothing in a new database)
-- check: nothing left owned by the provisioning role; the role has CONNECT, TEMPORARY, USAGE and CREATE (each
-- checked alone); PUBLIC has no CONNECT or TEMPORARY (a NULL ACL counts as the defaults)
```

A failed check raises (`StoreRoleCheckFailed`, `OwnershipNotMoved`), the transaction rolls back and the provisioner
raises `ProvisioningFailed`. The log line and the backfill report name the check that failed (privileged attribute,
member of another role, unexpected member, access, leftover objects), never a role name. If a re-run reports an
unexpected member, inspect `pg_auth_members` for the store role (who was granted it, and by whom) before revoking
anything.

- The returned connection string signs in as `store_<id>`; no other store's role (and no `PUBLIC` member) can connect
  to that database. The store role owns every object in it (it creates them when migrating). The provisioning role
  keeps access through its membership.
- The **database** stays owned by the provisioning role: Neon records that owner and may set it back, and access
  through the explicit grants does not depend on who owns it. The store role cannot alter or drop its database and has
  no `CREATE` on it, so a store migration cannot `CREATE SCHEMA` or `CREATE EXTENSION` without an extra grant.
- **Every call sets a new password** (`secrets.token_urlsafe(32)`), so a re-run rotates it and the previous string stops
  working. Store the string `create_database` returns. The provisioning job calls it under the store row lock and always
  replaces the stored one, so two deliveries cannot cross. Any other caller must do the same: never run
  `create_database` for one store concurrently, or the last password set and the last string saved could differ.
- The role is created with SQL, never with the Neon roles API (API roles join `neon_superuser`). It has only `LOGIN`.
- Identifiers are validated and quoted; the password is validated against its URL-safe alphabet and quoted as a literal
  (DDL takes no bind parameters, and Neon refuses pre-hashed passwords). It is never logged or put in an exception;
  failures log the exception class name only. Sentry drops SQL (`query`) breadcrumbs, which would carry the statement.
- `get_store_session` refuses a decrypted string whose database is not `store_<id>` or whose user is another store's
  role (`StoreDatabaseUnavailable`). Every provisioner version named databases `store_<id>`, so the database check
  refuses no existing store. A string still on the shared role opens with a warning until the backfill has run.
- Engines are built only in `store_sessions.py`: both provisioners and the backfill reach a store database through
  `store_sessions.open_admin_connection` (one transaction, `lock_timeout` 10 s).
- Manual tooling in a store database: connect as the provisioning role and `SET ROLE "store_<id>"` first, so anything
  you create belongs to the store role.
- Known limits (ADR-005): the plaintext password is in the DDL (Neon refuses hashed ones), so a failing statement can
  reach the Postgres server log (treat those logs as sensitive; raise `log_min_error_statement` where allowed); Neon `delete_database` cannot drop a role whose database is already gone.

### Existing stores: `commands.backfill_store_roles` (owner runbook)

Stores provisioned before KAN-238 still connect as the shared role. Per environment, after deploying KAN-238, with that
environment's `DATABASE_URL` and `STORE_DB_ENCRYPTION_KEY` (never from CI or a deploy):

1. Smoke-test once on a non-production Neon branch: provision a store, check its string signs in through the pooled
   endpoint and another store's string is refused on its database.
2. Pause `migrate_stores` and provisioning for the run.
3. Dry run, then the real run:

   ```bash
   uv run python -m commands.backfill_store_roles --all --dry-run   # lists what would move; changes nothing
   uv run python -m commands.backfill_store_roles --all             # every ACTIVE and PROVISIONING store with a database
   uv run python -m commands.backfill_store_roles --store-id <id>   # one store (repeatable)
   # add --continue-on-error to go past a failing store (the exit code is still 1)
   ```

   It prints the platform host and database name first (never credentials), then one line per store (ids only).
4. **Required:** reset the `NEON_ROLE_NAME` password (Neon console or API) and update it wherever the backend reads it;
   if the platform `DATABASE_URL` signs in as the same role, update that too. Until then every string written before
   KAN-238, and any copy of one, still opens every store. The command prints this step after a run that moved stores.
5. Resume `migrate_stores` and provisioning. Optionally close the platform database to store roles, as its owner:
   `GRANT CONNECT ON DATABASE <platform db> TO <platform role>;` then
   `REVOKE CONNECT ON DATABASE <platform db> FROM PUBLIC;` (store roles can read nothing there, but can see the catalog).

Per store, under the store row lock and in one transaction on the store database (direct endpoint): `apply_store_role`,
whose `move_owned_objects` step gives the role every schema, table (with its indexes and owned sequences), view,
materialized view, sequence, function and type the shared role owns there, including `store_alembic_version`, and rolls
back if `pg_shdepend` still lists anything owned by the shared role in that database (extensions excepted; other kinds,
extension members and default privileges excepted). Large objects, collations, conversions, operators, operator classes
and families, statistics objects, publications, text search dictionaries and configurations, foreign data wrappers,
foreign servers, non-extension procedural languages and event triggers are not moved: they fail that store and leave it untouched,
and need `ALTER ... OWNER TO "store_<id>"` by hand (as the provisioning role) before a re-run. Then the new string is
encrypted onto the row, and ownership is moved once more, in case a migration on the old string ran between the DDL
commit and the row flip. It never runs `REASSIGN OWNED BY` the shared role (that would move every database the role
owns). A store already on its own role is checked again: anything the shared role still owns there is moved, over the
provisioning role's own direct string, fetched from the configured provisioner before any platform row is locked;
otherwise it is skipped, as are stores with no database, so a re-run is safe (`--dry-run` lists such a store as
`would repair`). The command therefore needs the same provisioner settings as provisioning (`STORE_DB_PROVIDER` and,
for neon, `NEON_*`), besides `DATABASE_URL` and `STORE_DB_ENCRYPTION_KEY`; a failing lookup fails only that store.

The few current test stores may instead be archived and recreated: new stores get their role at provisioning. Step 4
still applies.

Both providers implement the `DatabaseProvisioner` protocol. The database is named `store_<store id>`. The id must match
`^[a-z0-9]{8,40}$` (cuid and cuid2 ids do), otherwise `InvalidStoreId` is raised before anything reaches the database or
the API. Identifiers cannot be bound parameters, so the validated name is also quoted; values are always bound.

Errors derive from `ProvisioningError` and carry only the store id: `InvalidStoreId`, `ProvisioningFailed`,
`ProvisionerNotConfigured` (lists the missing variable names, never values). Connection strings and the Neon API key are
never logged or placed in an exception; underlying driver and HTTP errors are dropped (`from None`).

## Configuration

| Variable            | Purpose                                                                                              |
| ------------------- | ---------------------------------------------------------------------------------------------------- |
| `STORE_DB_PROVIDER` | `local` (default, development only) or `neon`. Any other value fails at startup.                     |
| `NEON_API_KEY`      | Neon API key (secret). Required only when `neon` is selected.                                        |
| `NEON_PROJECT_ID`   | Neon project that holds store databases. Required for `neon`.                                        |
| `NEON_BRANCH_ID`    | Branch (for example `br-...`) the databases are created on. Required for `neon`.                     |
| `NEON_ROLE_NAME`    | Provisioning role: creates each database and its store role (needs `CREATEROLE`, which Neon project roles have). Required for `neon`. |
| `NEON_API_BASE_URL` | Optional. Defaults to `https://console.neon.tech/api/v2`. Must be `https` on `neon.tech`.            |

The `NEON_*` values stay optional at startup. Selecting `neon` without the required ones fails when the provisioner is
built (`ProvisionerNotConfigured`, naming the missing variables), not at import. `NEON_API_BASE_URL` is validated at
startup (https and a `neon.tech` host only) so the Bearer key can never go over plain http or to another host.

## Local provider

`LocalDatabaseProvisioner` reuses the **platform engine** (`app.core.database.engine`) for an `AUTOCOMMIT` admin
connection, because ruff `TID251` forbids creating engines outside `database.py` and `store_sessions.py`. It runs
`CREATE DATABASE "store_<id>"` after checking `pg_database`, then the store role SQL above through
`open_admin_connection` on the new database (the platform credentials pointed at it). On delete it
runs `DROP DATABASE IF EXISTS ... WITH (FORCE)` (Postgres 13+) and `DROP ROLE IF EXISTS "store_<id>"`. The `DATABASE_URL`
role therefore needs `CREATEDB` and `CREATEROLE` (the Docker superuser has both). The returned string is the platform URL
with the database, user and password swapped; it carries no `sslmode`.

**Development only.** Store roles live on the same server as the platform database and the admin connection is the
platform role. `get_database_provisioner` therefore refuses `STORE_DB_PROVIDER=local` outside local and test (and Vercel
preview/development), raising `ProvisionerNotConfigured`. **Production must use Neon.**

## Neon provider

`NeonDatabaseProvisioner` calls the Neon API v2 over httpx with `Authorization: Bearer $NEON_API_KEY` (30 s timeout):

| Step                 | Request                                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| exists / idempotency | `GET /projects/{NEON_PROJECT_ID}/branches/{NEON_BRANCH_ID}/databases`                                                     |
| create               | `POST` the same path, body `{"database": {"name": "store_<id>", "owner_name": NEON_ROLE_NAME}}`; `409` counts as created |
| admin connection     | the same `connection_uri` with `pooled=false`: the store role SQL runs as `NEON_ROLE_NAME` over the direct endpoint       |
| connection string    | `GET /projects/{NEON_PROJECT_ID}/connection_uri?branch_id=&database_name=&role_name=&pooled=true`, field `uri`, with the user and password swapped for the store role |
| delete               | if the database exists: `REASSIGN OWNED BY "store_<id>" TO CURRENT_USER`, `DROP OWNED`, `DROP ROLE` on the direct endpoint; then `DELETE /projects/{NEON_PROJECT_ID}/branches/{NEON_BRANCH_ID}/databases/store_<id>`; `404` is fine |

The pooled URI matches the session factory, which turns off asyncpg's statement cache for PgBouncer (KAN-54). Neon runs
these changes as asynchronous operations; a locked branch answers with an error that surfaces as `ProvisioningFailed`, and
the caller may retry because `create_database` is idempotent.

Neon applies a new database asynchronously; if the admin connection runs before the database is reachable it fails as
`ProvisioningFailed` and the job retries.

**Partial failure.** `create_database` is several calls (create, admin URI, role SQL, pooled URI). If the create succeeds but
the URI call fails, an empty database is left behind and `ProvisioningFailed` is raised. The caller must retry
`create_database` (it finds the database and only fetches the URI) or call `delete_database` to clean up. Tests use `httpx.MockTransport`; the real API is not called.

## Tests

- `tests/services/test_store_provisioning.py`: name validation and injection attempts, Neon create/exists/delete/
  idempotency/conflict/error paths with a mocked HTTP layer, no secrets in errors or logs, factory selection.
- `tests/services/test_store_provisioning_local.py`: the local provider against a fake engine (exact quoted statements,
  idempotency, the concurrent-create race, wrapped driver and connection errors), the factory and the settings validators.
- `tests/services/test_store_provisioning_contract.py`: the same behaviours run over both providers.
- `tests/services/test_store_provisioning_e2e.py`: the local provider on a real Postgres. Needs `TEST_DATABASE_URL`
  (database name ending `_test`, role with `CREATEDB` and `CREATEROLE`); skipped otherwise.
- `tests/services/test_store_roles_e2e.py` (KAN-238): on a real Postgres, as a non-superuser `CREATEDB CREATEROLE`
  role (Neon's shape): store A's credential is refused on store B's database (`42501`), a re-run rotates the password
  (old one `28P01`), role attributes, grants and the `PUBLIC` revoke, access survives the database owner moving to
  another role and back, a reused pre-KAN-238 database is handed over, delete drops the role, the Neon release SQL, a
  store role reads nothing in the platform database, and the backfill (every object moved, other databases of the
  shared role untouched, dry run, default selection, re-run skipped, `--continue-on-error`, an unmovable object kind
  rolls the store back, tables created between the DDL and the row flip are moved, and a later real store revision
  applies as the store role). Names carry `k238` and an epoch; stale ones are swept.
- `tests/services/test_store_roles.py`, `tests/services/test_store_role_backfill.py`,
  `tests/commands/test_backfill_store_roles.py`: validation, quoting, reports, exit codes.

```bash
docker run -d --name kan55-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=kan55_test -p 55455:5432 postgres:17
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55455/kan55_test uv run pytest tests/services/test_store_provisioning_e2e.py tests/services/test_store_roles_e2e.py
docker rm -f kan55-pg
```
