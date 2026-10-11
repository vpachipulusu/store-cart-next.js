# Architecture

**Last updated:** 2026-10-11
**Decisions:** every decision is recorded in [docs/adr](../adr/README.md). The plan's decision table (D1 to D23) is in [storecart-plan.md](../../.claude/plans/storecart-plan.md).

## Monorepo layout

```
store-cart-next.js/
├── nextjs-frontend/     Next.js 16 app (App Router). Vercel project 1.
├── fastapi_backend/     FastAPI service (uv). Vercel project 2, entry api/index.py.
├── docs/adr/            Architecture decision records (ADR-001 to ADR-010).
├── docs/developer/      This documentation.
└── .claude/             Plan, Jira backlog, agent instructions.
```

Key folders on `main`:

- `nextjs-frontend/src/`: `app/` (route groups `(admin)`, `(auth)`, plus `actions/`, `api/`, `dashboard/`, `pricing/`), `components/`, `lib/` (`db/`, `firebase/`, `stripe/`, `services/`, `middleware/`), `config/`, `__tests__/` (`unit/`, `integration/`, `e2e/`).
- `fastapi_backend/`: `app/` (`main.py`, `config.py`, `database.py`, `models.py`, `schemas.py`, `users.py`, `email.py`, `routes/`), `api/index.py` (Vercel entry point), `commands/` (OpenAPI generation), `alembic_migrations/`, `tests/`, `watcher.py`, `start.sh`, `Dockerfile`.

## Current state (`main`)

The repo is still the boilerplate with the target not yet built:

- **The frontend reaches the database itself.** Server actions, route handlers and admin pages use the Prisma client (`src/lib/db/client.ts`, schema in `prisma/schema.prisma`). Firebase Admin, Stripe and Resend are also called from the frontend.
- **The backend is the unmodified template structure.** It has fastapi-users auth, an `Item` example model and routes, and fastapi-mail. The frontend does not call it yet.
- **`fastapi_backend/vercel.json`** runs `alembic upgrade head` as part of the build.
- **`app/database.py`** uses `NullPool`, which suits serverless.

## Target state (Foundation complete)

```
Browser
   |  pages, server actions, route handlers (only Next.js is reachable)
   v
Next.js server  (nextjs-frontend, Vercel)
   |  X-Internal-Key + X-Session-Token            (ADR-003)
   v
FastAPI  (fastapi_backend, Vercel serverless)
   |  SQLAlchemy 2 async, NullPool
   v
Platform Postgres (Neon)
      later (E7): one Postgres per store
```

Rules:

- The browser calls only the Next.js server. The backend allows no browser origins ([ADR-003](../adr/0003-nextjs-to-fastapi-authentication.md)).
- The frontend holds no database credentials and no server secrets once Foundation is complete (KAN-51, E6).
- Responses use the envelope `{ success, data?, error? }` (D17, [ADR-008](../adr/0008-api-client-generation.md)).

## Request flow

1. The browser sends a request to Next.js: a page load, a server action POST, or a route handler call.
2. The Next.js server reads the `session` cookie and calls FastAPI through the generated typed client ([ADR-008](../adr/0008-api-client-generation.md)). It sends `X-Internal-Key` (proves the caller is our Next.js server) and `X-Session-Token` (the forwarded Firebase session cookie, which proves the user).
3. FastAPI checks the service key first, before any other work. It then verifies the Firebase session, including revocation, and resolves the merchant. The layering follows [ADR-004](../adr/0004-backend-layering.md).
4. FastAPI returns the envelope. Next.js renders the page or returns the action result. The browser never sees FastAPI.

## Data

- **Platform database:** accounts, organisations, memberships, billing and the audit log ([ADR-010](../adr/0010-accounts-and-payments-model.md)). Migrations run at deploy.
- **Store databases (E7):** one Postgres database per store ([ADR-005](../adr/0005-per-store-database-access.md)). This is provisional until the latency spike KAN-115 reports.
- **Store migrations** run from CI and never inside a request. Store migrations must be backward compatible.

## Architecture decision records

| ADR | Topic | Plan decisions |
|---|---|---|
| [001](../adr/0001-adopt-nextjs-fastapi-template.md) | Adopt the nextjs-fastapi-template backend | D20, D23 |
| [002](../adr/0002-hosting-on-vercel.md) | Hosting: two Vercel projects and serverless services | D10, D13, D18, D19 |
| [003](../adr/0003-nextjs-to-fastapi-authentication.md) | Authentication from the Next.js server to FastAPI | D14, D21 |
| [004](../adr/0004-backend-layering.md) | Backend layering | D15 |
| [005](../adr/0005-per-store-database-access.md) | Per-store database access | D1, D15 |
| [006](../adr/0006-docker-role.md) | Docker for local development and CI only | D20 |
| [007](../adr/0007-rate-limit-keys.md) | Rate limits keyed by user, organisation or store | new |
| [008](../adr/0008-api-client-generation.md) | Typed API client generated from OpenAPI | D16, D17 |
| [009](../adr/0009-email-with-resend.md) | Email through Resend from the backend | D22 |
| [010](../adr/0010-accounts-and-payments-model.md) | Account structure, seller of record and platform revenue | D3, D4, D9 |

The ADRs are currently *Proposed*, awaiting product-owner sign-off on KAN-29. The architect's review fixes to ADR-001, ADR-003, ADR-004, ADR-005 and ADR-007 are merged.
