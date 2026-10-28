# ADR-005: Per-store database access

- **Status:** Accepted by the product owner, 2026-10-12. The one-database-per-store choice (D1) was provisional until the KAN-115 spike; the spike (2026-10-16) found no blocking cost in the numbers it could take, so D1 is **provisionally accepted** with the shared-project topology for launch (see [KAN-115 spike results](#kan-115-spike-results)). One check remains before E7: re-measure the store database from inside Vercel.
- **Date:** 2026-10-11
- **Plan decisions:** D1 (tenant data isolation), D15 (SQLAlchemy 2 async, asyncpg, NullPool, two Alembic trees)
- **Jira:** KAN-29; spike KAN-115; carried out in KAN-30 (seam) and E7 (KAN-52 …)

## Context

Each merchant organisation runs several stores. Data crossing between merchants is the most serious risk in
the plan. The backend runs as serverless functions ([ADR-002](0002-hosting-on-vercel.md)), so it cannot keep
long-lived connection pools, and every store database adds connection setup cost to cold requests.

## Decision

### Tenant isolation (D1, accepted after KAN-115)

One Postgres database per store on Neon, plus one platform database. The platform database holds users,
organisations, memberships, billing, the audit log and the store registry (each store's database location,
schema version and status).

**Why:** a missing `WHERE store_id = …` cannot leak another store's data; a store can be exported, restored or
deleted as a unit; and per-store schema versions allow staged migrations.

**Topology: a database inside one shared Neon project (decided for launch).** A store can be a database inside
a shared Neon project, or its own Neon project. With a shared project, stores share compute, so isolation is at
the data level only: one busy store *can* still slow others, and cold starts are per project, not per store.
With one project per store, compute is isolated too, but cold starts and cost grow with the number of stores.
KAN-115 measured the shared-project option and found it acceptable. One project per store stays an option for
a single large merchant later; the provisioner and the session provider already hide the topology. E7 (KAN-52)
may refine it.

### One Postgres role per store (KAN-238, decided 2026-10-25)

**Decision:** every store database has its own login role, `store_<store id>` (the database's name), which owns
every object in it, and `PUBLIC` loses `CONNECT` (and `TEMPORARY`) on it. The store's connection string signs in
as that role, so one store's credential cannot open another store's database: Postgres refuses it (`42501`),
whatever the application does. One credential per store; it stays in `stores.connection_string_encrypted`.

**Before:** every store string carried the shared `NEON_ROLE_NAME` password, so isolation was per database, not
per credential. A wrong store-to-database mapping, or one leaked store string, exposed every store in the
project. Copying an encrypted string onto another store's row already failed (the store id is bound into the
AES-GCM associated data, KAN-53); a plaintext leak did not.

**How it is built** (`app/services/store_roles.py`, used by both provisioners):

- The role is created with SQL (`CREATE ROLE ... LOGIN PASSWORD ...`), not the Neon roles API: API roles join
  `neon_superuser` (`pg_read_all_data`, `pg_write_all_data`, `CREATEDB`, `CREATEROLE`, `BYPASSRLS`), SQL roles
  get only the default `PUBLIC` privileges (Neon docs, *Manage roles*). The store role has no attribute but
  `LOGIN`.
- The password is `secrets.token_urlsafe(32)` (about 256 bits; Neon asks for 60). DDL takes no bind parameters,
  so names are checked against `^store_[a-z0-9]{8,40}$` and quoted, and the password is checked against its
  URL-safe alphabet and quoted as a literal. Neon refuses pre-hashed passwords, so the plaintext is sent; it is
  never logged, never placed in an exception, and SQL breadcrumbs are dropped before anything reaches Sentry.
- Then, as the provisioning role, connected to the store database, in one transaction whose first statement pins
  `search_path = pg_catalog, pg_temp` (10 s `lock_timeout`), under the store's migration advisory lock (the one
  `store_migrations` takes, so role setup and a migration of the same store never interleave). The store role has
  `CREATE` on `public`, so without the pinned path a look-alike function or operator it planted there (a better
  argument match than pg_catalog's) would run as the provisioning role (the CVE-2018-1058 pattern); every function
  call in the admin SQL is also schema-qualified, as defence in depth:
  - `GRANT store_<id> TO CURRENT_USER WITH INHERIT TRUE, SET TRUE`. On Postgres 16+ a `CREATEROLE` role gets
    `ADMIN` on the roles it creates but not membership; `SET` is needed for `ALTER ... OWNER TO` the store role
    and `REASSIGN OWNED BY` it, `INHERIT` keeps the provisioning role's access for re-runs, deletion and
    repairs by hand. Requires Postgres 16+ (Neon projects run 16 or 17).
  - `REVOKE CONNECT, TEMPORARY ON DATABASE ... FROM PUBLIC`; `GRANT CONNECT, TEMPORARY ON DATABASE ... TO
    store_<id>`; `GRANT USAGE, CREATE ON SCHEMA public TO store_<id>`.
  - Every object the provisioning role owns in that database is given to the store role (none in a new
    database; see the migration path), with a `pg_shdepend` check that nothing is left.
  - `CONNECTION LIMIT -1`, `VALID UNTIL 'infinity'` and `RESET ALL` (role-wide and in its database) on every run.
  - Checks, each rolling the transaction back on failure: the role holds no privileged attribute, is a member of
    no role and has no member but the provisioning role (so a re-run never blesses a role someone widened); it
    has each of `CONNECT`, `TEMPORARY`, `USAGE` and `CREATE` on `public`, checked one by one (a `GRANT` that
    cannot apply only warns); `PUBLIC` has no `CONNECT` or `TEMPORARY`, counting a `NULL` ACL as the defaults.
- **The database itself stays owned by the provisioning role.** Neon's control plane records `owner_name` from
  the create call and may set the owner back; and a grant an owner makes to itself merges into its owner entry
  and moves with ownership, so a store role that *owned* its database would lose all access on such a reset.
  Access through grants from the provisioning role does not depend on who owns the database:
  `test_access_does_not_depend_on_who_owns_the_database` moves the owner to a third role and back and the store
  role keeps working throughout. It also means the store role cannot `ALTER` or `DROP` its database, and has no
  `CREATE` on it: a future store migration cannot `CREATE SCHEMA` or `CREATE EXTENSION` (grant it, or run that
  step as the provisioning role, when one is needed).
- Neon: the API still creates the database; the role SQL runs over the direct (unpooled) endpoint. Local
  (`STORE_DB_PROVIDER=local`, development only): `CREATE DATABASE`, then the same SQL.
- `create_database` is idempotent and **rotates**: a re-run keeps the database, role and data and sets a new
  password, so the caller stores the string it gets back. The provisioning job calls it under the store row
  lock and always replaces the stored string, so a duplicate QStash delivery can neither rotate the password of
  a store that has moved on nor cross another delivery. A re-provision that reuses the orphan database of a run
  from before KAN-238 hands its objects to the store role too. Deleting a store drops its role (Neon:
  `REASSIGN OWNED BY` *the store role* to the provisioning role, then `DROP ROLE`, before the API deletes the
  database).
- `get_store_session` refuses a decrypted string whose database is not `store_<id>` or whose user is another
  store's role. Every provisioner version named its databases `store_<id>` (KAN-55 onwards), so no stored
  string is refused by the database check. A string still on the shared role is accepted with a warning until
  the backfill below has run.
- The store role owns every object in its database and may create in `public`, so the store migrations
  (`migrate_stores`, which use the store's own string) keep working.
- The topology stays hidden: callers still see only `DatabaseProvisioner.create_database(store_id)` (a string)
  and `get_store_session(store_id)`. Moving a store to its own Neon project later changes neither.
- Manual tooling: connect as the provisioning role and `SET ROLE store_<id>` before creating anything in a
  store database, so new objects belong to the store role.

**Threat model.** It stops: one leaked store string, a wrong row-to-database mapping, and a bug that opens a
store session with another store's string, from reaching any other store's data. It does not stop:

- **The provisioning credential is still privileged.** `NEON_ROLE_NAME` (and `NEON_API_KEY`) can create roles
  and is a member of every store role. Anyone holding it reaches every store. It lives only in the backend's
  environment and never in a store row, **once the backfill has run and its password has been reset** (below):
  until then every string written before KAN-238, and any copy of one (logs, dumps, old backups), carries it.
- **The platform database.** A store role can *connect* to any database where `PUBLIC` keeps `CONNECT`, which
  includes the platform database when it shares the Neon project (or, locally, the same server). It can read
  nothing there: platform tables belong to the platform role and grant nothing to `PUBLIC`, and since Postgres
  15 `PUBLIC` cannot create objects in `public`. It can see catalog metadata (table and role names). Owner
  step to close it, as the platform database's owner:
  `GRANT CONNECT ON DATABASE <platform db> TO <platform role>;` then
  `REVOKE CONNECT ON DATABASE <platform db> FROM PUBLIC;` (grant first, so the platform role keeps access; add
  any other role that must connect, such as a read-only reporting role).
- Compute is still shared (see Topology). Rotation of a store's password is a re-run of `create_database`; there
  is no scheduled rotation.
- **The password crosses the wire in DDL.** Neon refuses pre-hashed passwords, so `CREATE/ALTER ROLE ...
  PASSWORD '<plaintext>'` is sent (over TLS to Neon). The application never logs it, but Postgres can: a failing
  statement is written to the server log (`log_min_error_statement`), and `pg_stat_statements` may keep utility
  statement text (readable by `neon_superuser` members). Accepted: such a password opens one store database
  only, and a re-run replaces it.
- **Leftover roles.** Neon `delete_database` drops the store role only while the database still exists (it must
  connect to it). A role whose database was already deleted elsewhere stays; it can connect to no store
  database, and its password exists only in that store's encrypted row. Remove it by hand if it matters.
- **Self-inflicted stalls.** A store role can take the migration advisory lock in its own database
  (`pg_advisory_lock(5735701)`) and so stall that store's migrations and role re-runs. It affects only that store.

**Migration path for existing stores** (owner steps, per environment, after KAN-238 is deployed):

1. Smoke-test once on a non-production Neon branch: provision a store, check that its string signs in through
   the pooled endpoint and that another store's string is refused on its database.
2. Pause `migrate_stores` and provisioning (no store creation, no QStash deliveries) for the run.
3. `uv run python -m commands.backfill_store_roles --all --dry-run`, with that environment's `DATABASE_URL` and
   `STORE_DB_ENCRYPTION_KEY`. It prints the platform host and database (never credentials) and the stores that
   would move; nothing changes. Then run it without `--dry-run` (`--store-id ID` for one store; add
   `--continue-on-error` to go past a failing store, the exit code is still 1). `--all` takes every ACTIVE and
   PROVISIONING store with a database.
   For each store, under the store row lock, it connects with the store's current (shared role) string switched
   to the direct endpoint and, in one transaction under the store's migration advisory lock, runs the same SQL
   as provisioning: it creates the role, revokes `PUBLIC` `CONNECT`, grants the role its access, moves every
   object the shared role owns in the database (schemas, tables with their indexes and owned sequences, views,
   materialized views, sequences, functions, types and domains, including `store_alembic_version`) to the role,
   checks that nothing is left and that the role's access is in place, then re-encrypts the new string onto the
   row and moves ownership once more (a migration on the old string between the DDL commit and the row flip may
   have created tables as the shared role). The database stays owned by the shared role, as for new stores. It
   never uses `REASSIGN OWNED BY` the shared role, which would also move every other database that role owns.
   Object kinds it does not move (large objects, collations, conversions, operators, operator classes and
   families, statistics objects, publications, text search dictionaries and configurations, foreign data wrappers,
   foreign servers, non-extension procedural languages, event triggers) fail the check and leave that store untouched; the store schema
   creates none of them, and they need moving by hand (`ALTER ... OWNER TO`, as the provisioning role) before a
   re-run. Extension members and default privileges are not counted. A 10 s `lock_timeout` keeps it from
   queueing behind a long store transaction (it fails instead; re-run later). A store already on its role is
   checked again: anything the shared role still owns there (a failed post-flip pass) is moved over the
   provisioning role's own direct string, fetched from the provisioner before any platform row is locked (so a
   re-run needs the same `STORE_DB_PROVIDER` and `NEON_*` settings as provisioning; a failing lookup fails only
   that store); otherwise it is skipped, so a re-run is safe. `--dry-run` reports such a store as `would repair`.
4. **Required:** reset the `NEON_ROLE_NAME` password (Neon console or API) and update it wherever the backend
   reads it; if the platform `DATABASE_URL` signs in as the same role, update that too. Only then does a copy
   of a pre-KAN-238 string stop opening every store. The command prints this step after a run that moved stores.
5. Resume `migrate_stores` and provisioning. Optionally close the platform database to store roles (above).

The few existing test stores may instead be archived and recreated (then do step 4 as well).

**Follow-ups (not built here):** fail closed on shared-role strings in `get_store_session` once every
environment is backfilled (needs a setting in `config.py`); separate runtime and migration roles per store
(needs a platform model change); `CONNECTION LIMIT` and `statement_timeout` per store role; moving the
pooler-host logic (`direct_endpoint`) next to the other Neon URL handling.

**Why it was provisional:** the cost is connection setup per store on serverless, plus running migrations
across many databases. The **KAN-115 spike** measured the connection cost (below). The numbers are low enough
that neither fallback (a different backend host, or a shared database with `store_id` and row-level security,
the recorded dissent) is needed now.

### KAN-115 spike results

Measured 2026-10-16. All figures are wall-clock milliseconds for the work one request pays with `NullPool`:
build engine, connect through Neon's pooled endpoint, `SELECT 1`, dispose.

| Case | Where measured | n | Median | p95 |
|---|---|---|---|---|
| `/health` (no database) | Live Vercel backend (lhr1), from a dev machine | 30 | 215 | 380 |
| `/health/ready` (platform database) | Live Vercel backend, same | 30 | 278 | 358 |
| Store database, warm | Local harness against Neon eu-west-2 | 30 | 607 | 795 |
| Store database, first connect after ~7 min idle (Neon suspend) | Local harness | 1 | 1068 | n/a |
| Store database, next requests after that | Local harness | 5 | 370 | max 483 |

Also: creating a store database through the Neon API took 13.4 s (a provisioning job cost, not a request cost).
The cold first call to the platform database on Vercel was 907 ms (434 ms for `/health`).

**What this says**
- On Vercel, one platform-database connection and query adds about 63 ms median (278 vs 215).
- The store figures were taken from a development machine, where TLS and authentication round trips dominate
  (TCP connect to the host was 28 ms). They are not the Vercel figure; we infer they overstate it, because a
  development machine is farther from Neon than same-region compute, but that is not measured. Expected same-region cost is similar to the platform database (about 60-70 ms), which would
  put a request touching both databases near 340 ms median warm. That is an inference, not a measurement.
- A store database that has been idle long enough for Neon to suspend its compute costs roughly 0.5-0.7 s extra
  on the first request, once per idle period (1068 ms vs 607 ms warm median, or vs 370 ms for the five requests
  right after wake-up; the two baselines differ, which we put down to run-to-run noise on one sample). Acceptable for merchant dashboards. A
  storefront with traffic gaps would see it, so E7 should decide whether to turn off scale-to-zero for paid
  plans.
- The session provider worked as designed: a second database was created through `NeonDatabaseProvisioner` and
  reached through `build_engine`/`NullPool`, with no code change.

**Limits of this spike**
- Vercel deploys only from `main` (KAN-212) and no spike endpoint was deployed, so the store database was not
  queried from inside Vercel. Only the platform delta was measured there.
- The cold-start sample is one observation.
- Because of both, the first E7 story that adds a store-backed route must record median and p95 for it on
  Vercel, and revisit this section if the store path is more than about 150 ms over the platform path.

**Decision:** keep one database per store, in one shared Neon project, provisionally accepted pending the
Vercel re-measurement above; do not switch host or move to row-level security now. Revisit if that
re-measurement fails.

### Connections (D15)

- SQLAlchemy 2 async with asyncpg.
- `NullPool` on every engine: a connection lives for one request only. Pooling is done by **Neon's pooled
  endpoints** (PgBouncer in transaction mode), for both platform and store databases.
- asyncpg's prepared-statement caches are disabled on pooled connections (`prepared_statement_cache_size=0` in
  the SQLAlchemy URL and `connect_args={"statement_cache_size": 0}`), or statements are uniquely named,
  because transaction-mode PgBouncer cannot track them. KAN-112 verifies this against Neon.
- **Migrations use Neon's direct (unpooled) endpoint**: the platform migration at deploy and `migrate_stores`.
  DDL and advisory locks must not go through the pooler. Requests always use the pooled endpoint.
- TLS settings are passed to asyncpg through `connect_args`; asyncpg ignores a `sslmode` URL parameter.
- Platform and store models live in separate metadata with separate Alembic trees: `platform` and `store`.

### The store session seam

Store data is reached only through a `StoreSessionProvider` interface. A session needs a **grant**, which
says why the caller may touch that store:

```python
StoreGrant = MerchantStoreGrant | SystemStoreGrant

class StoreSessionProvider(Protocol):
    def session_for(self, grant: StoreGrant) -> AbstractAsyncContextManager[AsyncSession]: ...
```

- **`MerchantStoreGrant`** is issued by the `require_merchant` → store-access dependencies, after they check the
  Firebase session and the organisation membership against the platform database.
- **`SystemStoreGrant`** is for work with no merchant: QStash provisioning steps, issued only after the QStash
  signature is verified, and the `migrate_stores` CLI. It records which job asked for it, for the audit log.
- Python cannot stop a class being constructed elsewhere, so this is enforced by convention plus checks: grants
  are created only through factory functions in `tenancy/grants.py`; a lint rule bans constructing them anywhere
  else; and a test fails if any other module does.
- **Where the code lives:** the protocol and the grants are in `tenancy/`; the `NullPool` implementation is in
  `db/store/`, so the "engines only in `db/`" rule ([ADR-004](0004-backend-layering.md)) still holds.
- The first implementation opens a `NullPool` engine for the store's pooled endpoint. If KAN-115 leads to a
  shared database with row-level security, domain services stay the same, but models, migrations and the
  provider change: every store table gains `store_id` and RLS policies, and the provider sets the store with
  `SET LOCAL` inside the transaction (required behind transaction-mode PgBouncer).
- Engine creation stays in `db/`, and a lint rule enforces it.
- E7.7 adds a tenant-isolation test suite that runs against two organisations with several stores each, on
  real separate databases.

### Migrations

Store migrations must be backward compatible. They run from a GitHub Actions job (`migrate_stores`) in
batches that stop on the first failure, with each store's schema version tracked in the registry. They never
run inside a request.

## Alternatives considered

- **Shared database, `store_id` on every row, row-level security.** Cheapest to run and migrate; isolation
  depends on every query and policy being right. This is the fallback if KAN-115 fails.
- **Schema per store in one database.** Weaker isolation than separate databases; serverless connection costs
  barely change and migrations get harder.
- **Long-lived connection pools.** Not possible on serverless functions.

## Consequences

- Tenant routing lives in one interface, so the D1 decision can be revisited without touching domain code.
- Every store request pays connection setup through Neon's pooler; KAN-115 puts a number on it.
- Migrations and provisioning need their own tooling (E7) and monitoring for stores on mixed schema versions.
