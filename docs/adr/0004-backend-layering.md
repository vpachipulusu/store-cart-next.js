# ADR-004: Backend layering

- **Status:** Proposed
- **Date:** 2026-10-11
- **Plan decisions:** D15 (data access, layer placement)
- **Jira:** KAN-29; carried out in KAN-30

## Context

The template keeps routes, models and the database in a few flat modules (`main.py`, `models.py`,
`database.py`, `users.py`). StoreCart will have many domains (auth, organisations, billing, catalogue, orders)
and two kinds of database (platform and per store). Tenant isolation is the most serious risk in the plan, so
the place where a store database is opened has to be easy to find and control.

## Decision

`fastapi_backend/app/` is organised by layer, and dependencies only point downwards:

```
api/v1/        HTTP only: routers, request/response schemas, dependencies (auth, store access)
services/      business logic and transaction boundaries; no FastAPI imports
repositories/  SQLAlchemy queries for one aggregate each; no business rules
db/platform/   platform models, engine/session factory, Alembic tree "platform"
db/store/      store models, the NullPool StoreSessionProvider implementation, Alembic tree "store"
tenancy/       store lookup, membership checks, store grants and the StoreSessionProvider protocol (ADR-005)
core/          config (pydantic-settings), structured logging, error types and handlers, Sentry
```

Rules:
- Routers call services; services call repositories; repositories receive an `AsyncSession` and never create
  one.
- Engines and sessions are created only in `db/`. A lint rule bans `create_async_engine` and
  `async_sessionmaker` anywhere else.
- Services raise domain errors (`core/errors`). One exception handler turns them into the
  `{ success, data?, error? }` envelope ([ADR-008](0008-api-client-generation.md)) with the right HTTP status,
  with no stack traces or internal details.
- Logging is structured (JSON) through one logger set up in `core/`; no `print()`.
- Configuration comes only from `core/config`; required secrets are checked at startup.

## Alternatives considered

- **Keep the template's flat layout.** Fine for an example app; at StoreCart's size it would mix HTTP,
  business rules and tenant routing in the same modules.
- **Feature folders (one package per domain, each with its own layers).** Good later. Starting with layers
  keeps the database seam in one place while there are only a few domains; domain sub-packages can be added
  inside each layer as they grow.
- **Hexagonal architecture with ports for every dependency.** More ceremony than a small team needs. The one
  seam that must be swappable (store sessions) gets an explicit interface in ADR-005.

## Consequences

- Services and repositories can be unit-tested with a session fixture and no HTTP.
- New code has an obvious home, and review can check "no session created outside `db/`" mechanically.
- Some thin pass-through code (router → service → repository) for simple reads; accepted for consistency.
