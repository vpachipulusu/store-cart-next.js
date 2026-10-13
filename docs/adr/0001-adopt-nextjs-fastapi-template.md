# ADR-001: Adopt the nextjs-fastapi-template backend

- **Status:** Accepted by the product owner, 2026-10-12
- **Date:** 2026-10-11
- **Plan decisions:** D20 (tooling), D23 (folder names)
- **Jira:** KAN-29; carried out in KAN-25 (move) and KAN-30 (adaptation)

## Context

StoreCart started as a Next.js boilerplate that reads Postgres directly through Prisma, from server actions
and from some pages. Multi-tenancy (one database per store) and keeping secrets out of the frontend both
need a separate backend. Building one from scratch would take weeks that the 4–5 week Foundation budget
does not have.

[vintasoftware/nextjs-fastapi-template](https://github.com/vintasoftware/nextjs-fastapi-template) (MIT)
already provides a FastAPI service with uv, async SQLAlchemy, Alembic, OpenAPI client generation, Docker
Compose, pre-commit and a Vercel serverless entry point.

## Decision

Adopt the template's backend as `fastapi_backend/` and keep the template's folder names
(`nextjs-frontend/`, `fastapi_backend/`) so upstream changes stay easy to compare (D23).

Keep:
- the uv project (`pyproject.toml`, `uv.lock`), renamed to StoreCart, with its old pins upgraded (for example
  ruff `<0.2`) before anything is built on it;
- `api/index.py` (see [ADR-002](0002-hosting-on-vercel.md)); the template's `vercel.json` and `vercel.prod.json` are replaced by the root `vercel.json` ([ADR-011](0011-single-vercel-project-with-services.md));
- the `NullPool` engine (see [ADR-005](0005-per-store-database-access.md));
- `generate_openapi_schema` and `watcher.py` (see [ADR-008](0008-api-client-generation.md));
- Docker Compose, pre-commit, Makefile and GitHub workflows, adapted (see [ADR-006](0006-docker-role.md)).
  These live at the upstream template's root and are **not yet in this repo**; KAN-26, KAN-111 and KAN-27 copy
  them in.

Tooling (D20): uv, ruff, mypy, pytest with pytest-asyncio, pre-commit hooks, Docker Compose for local
development, and Sentry.

Remove or change:

| Template piece | Change | Reason |
|---|---|---|
| fastapi-users (`users.py`, auth routes, `User` table, JWT secrets) | Remove | Firebase stays ([ADR-003](0003-nextjs-to-fastapi-authentication.md)) |
| fastapi-mail and `email_templates/` | Remove | Resend ([ADR-009](0009-email-with-resend.md)) |
| `Item` model, routes, migrations | Remove; new Alembic baseline | Example code |
| `Dockerfile` (root user, `curl … \| sh` uv install) | Harden: pinned uv image, non-root user | Supply-chain and container safety |
| `CORS_ORIGINS=["*"]` with credentials | Restrict (in practice, no browser origins) | The browser never calls the backend |
| `print()` in the user manager | Structured logging | Goes with fastapi-users anyway |
| `database.py` rebuilds the URL and drops its query string | Pass TLS settings through asyncpg `connect_args` | Neon's `sslmode` is otherwise lost, and asyncpg ignores it anyway ([ADR-005](0005-per-store-database-access.md)) |

The upstream MIT licence is kept in `fastapi_backend/`.

## Alternatives considered

- **Write a FastAPI service from scratch.** Full control, but rebuilds what the template already solves
  (serverless entry point, OpenAPI pipeline, Compose) and costs most of Foundation.
- **Keep everything in Next.js (server actions + Prisma).** No second service, but per-store database routing,
  background jobs and secret isolation would all live in the frontend, against D14 and the Foundation
  definition of done.
- **Use the template whole, including fastapi-users.** Would mean migrating every merchant account off
  Firebase for no product gain.

## Consequences

- Foundation starts from a working skeleton; KAN-30 is mostly deleting and hardening, not writing.
- We own the fork. Upstream fixes are compared and copied by hand; no automatic sync.
- Old pins and the template's insecure defaults (Dockerfile, CORS) are known debts, and KAN-30 must pay them
  before feature work.
