# ADR-005: Per-store database access

- **Status:** Proposed. The one-database-per-store choice (D1) is **provisional** until the KAN-115 spike.
- **Date:** 2026-10-11
- **Plan decisions:** D1 (tenant data isolation), D15 (SQLAlchemy 2 async, asyncpg, NullPool, two Alembic trees)
- **Jira:** KAN-29; spike KAN-115; carried out in KAN-30 (seam) and E7 (KAN-52 …)

## Context

Each merchant organisation runs several stores. Data crossing between merchants is the most serious risk in
the plan. The backend runs as serverless functions ([ADR-002](0002-hosting-on-vercel.md)), so it cannot keep
long-lived connection pools, and every store database adds connection setup cost to cold requests.

## Decision

### Tenant isolation (D1, provisional)

One Postgres database per store on Neon, plus one platform database. The platform database holds users,
organisations, memberships, billing, the audit log and the store registry (each store's database location,
schema version and status).

**Why:** a missing `WHERE store_id = …` cannot leak another store's data; a store can be exported, restored or
deleted as a unit; one large store cannot slow down others' queries; and per-store schema versions allow staged
migrations.

**Why provisional:** the cost is connection setup per store on serverless, plus running migrations across
many databases. The **KAN-115 spike** (≤3 days, after KAN-30 and KAN-112) routes one request to a second Neon
store database on Vercel and records median and p95 latency, cold starts included. If the result is not
acceptable, we revisit before E7 starts, with two options on the table: a different backend host, or a shared
database with `store_id` and Postgres row-level security (the recorded dissent). The outcome is recorded by
updating this ADR or superseding it.

### Connections (D15)

- SQLAlchemy 2 async with asyncpg.
- `NullPool` on every engine: a connection lives for one request only. Pooling is done by **Neon's pooled
  endpoints** (PgBouncer), for both platform and store databases.
- Platform and store models live in separate metadata with separate Alembic trees: `platform` and `store`.

### The store session seam

Store data is reached only through a `StoreSessionProvider` interface in `tenancy/`:

```python
class StoreSessionProvider(Protocol):
    def session_for(self, store: AuthorisedStore) -> AbstractAsyncContextManager[AsyncSession]: ...
```

- `AuthorisedStore` can only be created by the `require_merchant` → store-access dependencies, which check
  the Firebase session and the organisation membership against the platform database first. So no code path
  can open a store session for a store the caller has not been authorised for.
- The first implementation opens a `NullPool` engine for the store's pooled endpoint. If KAN-115 leads to a
  shared database with row-level security, only the provider changes: it would return a session on the shared
  database with `store_id` set for row-level security. Services and repositories stay the same.
- Engine creation stays in `db/` ([ADR-004](0004-backend-layering.md)), and a lint rule enforces it.
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
