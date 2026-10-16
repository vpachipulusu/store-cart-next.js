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

**Isolation limit in the shared project:** with one Neon role serving every store database, isolation is per
database, not per credential. A wrong store-to-database mapping, or a leaked privileged connection string,
exposes all stores in the project. The application chooses the database (`get_store_session`, with the backend
authorizing the store id). E7 should decide whether to create a role per store (`CREATE ROLE` plus
`REVOKE CONNECT ON DATABASE ... FROM PUBLIC`) so the database enforces it too.

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
