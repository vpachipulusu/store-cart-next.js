# Architecture

**Last updated:** 2026-10-12
**Decisions:** every decision is recorded in [docs/adr](../adr/README.md). The plan's decision table (D1 to D23) is in [storecart-plan.md](../../.claude/plans/storecart-plan.md).

## Monorepo layout

```
store-cart-next.js/
├── nextjs-frontend/     Next.js 16 app (App Router). Vercel service nextjs-frontend (public).
├── fastapi_backend/     FastAPI service (uv). Vercel service fastapi_backend (internal, entrypoint app.main:app).
├── docs/adr/            Architecture decision records (ADR-001 to ADR-011).
├── vercel.json          One Vercel project with the two services above (ADR-011).
├── docs/developer/      This documentation.
└── .claude/             Plan, Jira backlog, agent instructions.
```

Key folders on `main`:

- `nextjs-frontend/src/`: `app/` (route groups `(admin)`, `(auth)`, plus `actions/`, `api/`, `dashboard/`, `pricing/`), `components/`, `lib/` (`db/`, `firebase/`, `stripe/`, `services/`, `middleware/`), `config/`, `__tests__/` (`unit/`, `integration/`, `e2e/`).
- `fastapi_backend/`: `app/` (layered, see [Backend layout](#backend-layout-adr-004)), `api/index.py` (template file; the root `vercel.json` uses `app.main:app` instead), `commands/` (OpenAPI generation and check), `alembic_migrations/`, `tests/`, `watcher.py`, `start.sh`, `Dockerfile`, `TEMPLATE_LICENSE.txt` (the template's licence, kept as required).

### Backend layout (ADR-004)

KAN-30 adapted the template. The example `Item` model and routes, fastapi-users, fastapi-mail, fastapi-pagination and the template migrations are removed. What is built so far:

```
fastapi_backend/app/
├── main.py              create_app(): title "StoreCart API", request ID and error envelope, JSON logging, mounts the v1 router; `app` is the Vercel entrypoint
├── core/
│   ├── config.py        pydantic-settings (DATABASE_URL required, checked at startup)
│   ├── base.py          SQLAlchemy declarative Base (no settings import, so Alembic can load it)
│   ├── database.py      NullPool engine, session maker, SessionProvider protocol, DefaultSessionProvider
│   └── logging.py       JSON logging to stdout
├── api/
│   ├── deps.py          FastAPI dependencies: get_session_provider, get_session, service factories
│   ├── ids.py           OpenAPI operation ids
│   └── v1/              routers: health.py (GET /health, GET /health/ready), router.py
├── services/            business logic, no FastAPI imports (health.py)
└── repositories/        SQLAlchemy queries; receive an AsyncSession, never create one (base.py, health.py)
```

Not built yet (the ADR describes them): `db/platform`, `db/store`, `tenancy/`, `core/errors`, Firebase auth, rate limiting.

**Session seam.** Repositories take an `AsyncSession` in their constructor. The session comes from a `SessionProvider` (a `Protocol` in `core/database.py` with `session()`, an async context manager). `api/deps.get_session_provider()` returns the default provider (the platform database, NullPool). Tests override that one dependency with a fake provider. Per-store routing (ADR-005, E7) will add another provider implementation; it is interface only today.

**Alembic and platform models (KAN-36).** The platform models live in `app/models/platform/`, one aggregate per file, on a `Base` with its own naming-convention `MetaData`. The tree is a single baseline revision `0001` (`alembic_migrations/versions/0001_platform_baseline.py`) that creates the 11 boilerplate tables plus `organizations`, `memberships`, `invitations` and the `stores` registry. `alembic_migrations/env.py` connects with `DATABASE_URL_DIRECT` (Neon unpooled) when set, else `DATABASE_URL`. No deploy or build step runs `alembic upgrade head` against a deployed database (ADR-011); the backend workflow runs upgrade, `alembic check` and downgrade against a throwaway Postgres 17 service container. Differences from the Prisma schema are listed in [platform-models.md](platform-models.md).

**OpenAPI check.** `commands/check_openapi_schema.py` (pre-commit hook `openapi-schema-check`) still passes while `nextjs-frontend/openapi.json` does not exist; KAN-33 owns the client generation and will commit that file.

## Current state (`main`)

The repo is still the boilerplate with the target not yet built:

- **The frontend reaches the database itself.** Server actions, route handlers and admin pages use the Prisma client (`src/lib/db/client.ts`, schema in `prisma/schema.prisma`). Firebase Admin, Stripe and Resend are also called from the frontend.
- **The backend is the adapted template (KAN-30).** It has only a health route, the layered `app/` structure and the session seam; there is no auth, no models and no email yet. The frontend does not call it yet.
- **Root `vercel.json`** deploys one Vercel project with two services (ADR-011): `nextjs-frontend` is public, `fastapi_backend` is internal and reached through the `BACKEND_API_URL` binding. Migrations no longer run during the build.
- **`app/core/database.py`** uses `NullPool`, which suits serverless.
- **Deployment health (KAN-112).** The backend has no public route. `GET /api/health` on the frontend (`src/app/api/health/route.ts`) fetches `${BACKEND_API_URL}/health` server-side (3 s timeout, no cache) and returns `200 {"status":"ok"}`, or `503 {"status":"unavailable"}` with no detail when `BACKEND_API_URL` is unset, the backend is unreachable or it returns non-200; the cause is logged server-side. `src/proxy.ts` leaves it unauthenticated and exempt from rate limiting. No internal key header is sent because the backend defines none. `.github/workflows/post-deploy-smoke.yml` curls it after each successful Production deployment. **Migrations never run in a build or deploy step**; run `alembic upgrade head` deliberately and separately (ADR-011).

### Current auth flow (`main`)

1. The Firebase client SDK signs the user in and sends the ID token to the `verifyTokenAction` server action (`src/app/actions/auth-actions.ts`).
2. `verifyTokenAction` creates a Firebase session cookie with `createSessionCookie` (5 days) and sets it as the httpOnly `session` cookie. It no longer sets an `email-verified` cookie (KAN-123); it deletes any left over from an older deployment, and returns `claimsEmailVerified` from the verified ID token.
3. `src/proxy.ts` (the Next.js 16 proxy; the exported function is `proxy`) only checks that a credential exists. The protected pages (`/dashboard`, `/settings`, `/profile`, `/security`) and `/admin` need a `session` cookie; `/api/*` (except `/api/webhooks/` and `/api/health`) needs a `session` cookie or any `Bearer` header. It does not verify either value (KAN-137) and no longer reads the `email-verified` cookie (KAN-123): the edge cannot verify Firebase tokens, and that cookie is client-writable.
3a. Email verification is enforced server-side, from the signed `email_verified` claim in the session cookie, by `src/lib/auth/verified-session.ts` (`verifyVerifiedSessionCookie` always checks revocation; `getVerifiedUserId` is for server actions). The dashboard and admin layouts, the dashboard page, the user/notification/subscription actions, the admin actions and `admin-helpers` all go through it. An unverified user is sent to `/verify-email` (pages) or gets `Unauthorized` (actions). The verify-email page re-mints the session cookie once Firebase reports the email verified. This is the legacy Next.js boundary; the FastAPI guards (KAN-37) do not count for it.
4. The admin role is verified server-side: the admin layout (`src/app/(admin)/admin/layout.tsx`) and each admin server action (`src/app/actions/admin/*`) verify the session cookie with Firebase Admin and look up the `adminUser` record.
5. Vercel service bindings such as `BACKEND_API_URL` are not available in the proxy ([ADR-011](../adr/0011-single-vercel-project-with-services.md)).

### Feature areas on `main`

Boilerplate features that exist today and will be rebuilt behind FastAPI. Folded in from the retired `nextjs-frontend/GUIDE.md` (KAN-146); see also [admin-settings.md](admin-settings.md).

- **Customer dashboard** (`src/app/dashboard/`): home, `profile`, `settings` and `security` pages.
- **Admin portal** (`src/app/(admin)/admin/`): `users`, `subscriptions`, `analytics`, `seo`, `settings` and `audit-logs`. An admin needs an `AdminUser` record; create one with `node scripts/create-admin.mjs <email>` (the user must have signed up first). Admin actions are written to the audit log.
- **Billing** (`src/app/actions/subscription-actions.ts`, `src/app/api/webhooks/stripe/route.ts`): `createCheckoutSessionAction` starts a Stripe Checkout session, the Stripe webhook at `/api/webhooks/stripe` updates the database, and `createBillingPortalSessionAction` opens the billing portal. The pricing page adapts its call-to-action to the sign-in state.

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
| [002](../adr/0002-hosting-on-vercel.md) | Hosting: two Vercel projects and serverless services (two-project part superseded by ADR-011) | D10, D13, D18, D19 |
| [003](../adr/0003-nextjs-to-fastapi-authentication.md) | Authentication from the Next.js server to FastAPI | D14, D21 |
| [004](../adr/0004-backend-layering.md) | Backend layering | D15 |
| [005](../adr/0005-per-store-database-access.md) | Per-store database access | D1, D15 |
| [006](../adr/0006-docker-role.md) | Docker for local development and CI only | D20 |
| [007](../adr/0007-rate-limit-keys.md) | Rate limits keyed by user, organisation or store | new |
| [008](../adr/0008-api-client-generation.md) | Typed API client generated from OpenAPI | D16, D17 |
| [009](../adr/0009-email-with-resend.md) | Email through Resend from the backend | D22 |
| [010](../adr/0010-accounts-and-payments-model.md) | Account structure, seller of record and platform revenue | D3, D4, D9 |
| [011](../adr/0011-single-vercel-project-with-services.md) | One Vercel project with services | D10, D13, D14 |

All eleven ADRs were accepted by the product owner on 2026-10-12 (KAN-29). ADR-005's one-database-per-store choice (D1) stays provisional until the KAN-115 spike, and the two-project part of ADR-002 is superseded by ADR-011. The architect's review fixes to ADR-001, ADR-003, ADR-004, ADR-005 and ADR-007 are merged.
