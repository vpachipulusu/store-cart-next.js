# Getting started

**Last updated:** 2026-10-12

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 22.12 or later (22 or 24) | Team standard. `nextjs-frontend/package.json` declares `engines.node ^22.12.0 || ^24.0.0`. |
| npm | 10 or later | npm only. Do not use pnpm or yarn. |
| Python | 3.12 | Required by `fastapi_backend/pyproject.toml` (`>=3.12,<3.13`). |
| uv | current (CI uses 0.8.12) | Manages the backend environment and dependencies. |
| PostgreSQL | reachable instance | A local server on port 5432, or a development database. See [Local databases](#local-databases). |

Docker is optional. `fastapi_backend/Dockerfile` exists, but there is no `docker-compose.yml` yet (it arrives with KAN-26).

## Local databases

Create a role, a development database and a separate test database on your local Postgres (port 5432):

```bash
psql -h localhost -p 5432 -U postgres -c "CREATE ROLE <user> LOGIN PASSWORD '<password>';"
psql -h localhost -p 5432 -U postgres -c "CREATE DATABASE <db> OWNER <user>;"
psql -h localhost -p 5432 -U postgres -c "CREATE DATABASE <test_db> OWNER <user>;"
```

The URLs then have this shape:

- Backend `DATABASE_URL`: `postgresql+asyncpg://<user>:<password>@localhost:5432/<db>`
- Frontend `DATABASE_URL` (Prisma): `postgresql://<user>:<password>@localhost:5432/<db>`

The backend tests need no database (they use fake sessions), so there is no backend `TEST_DATABASE_URL` any more.

## Clone

```bash
git clone https://github.com/vpachipulusu/store-cart-next.js.git
cd store-cart-next.js
```

The repository has two apps: `nextjs-frontend/` and `fastapi_backend/`. Each has its own setup below.

## Frontend (`nextjs-frontend/`)

```bash
cd nextjs-frontend
npm ci
npm run db:generate
npm run typecheck
```

`npm ci` usually generates the Prisma client through the `@prisma/client` postinstall, but run `npm run db:generate` to be sure before `npm run typecheck`. It is required after any change to `prisma/schema.prisma`.

### Frontend environment

```bash
cp .env.example .env
```

Fill in the values from the team's secret store. Never commit `.env`. The list below gives names only. `nextjs-frontend/.env.example` is the reference for the variables `main` uses today; rows marked "not yet in `.env.example`" are planned.

| Group | Variable names | Notes |
|---|---|---|
| Database | `DATABASE_URL` | Server-only. Must leave the frontend in KAN-51 (E6). |
| Firebase client | `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`, `NEXT_PUBLIC_FIREBASE_PROJECT_ID`, `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`, `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`, `NEXT_PUBLIC_FIREBASE_APP_ID` | Public by design. |
| Firebase Admin | `FIREBASE_ADMIN_PROJECT_ID`, `FIREBASE_ADMIN_CLIENT_EMAIL`, `FIREBASE_ADMIN_PRIVATE_KEY` | Server-only. Must leave the frontend in KAN-51. |
| Stripe | `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_FREE`, `STRIPE_PRICE_ID_PRO`, `STRIPE_PRICE_ID_ENTERPRISE` | Secret keys are server-only. |
| Email | `RESEND_API_KEY` | Server-only. Email moves to the backend ([ADR-009](../adr/0009-email-with-resend.md)). |
| Auth | `NEXTAUTH_SECRET` | Server-only. |
| App | `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_APP_NAME`, `APP_ID`, `APP_NAME`, `NODE_ENV`, `LOG_LEVEL` | |
| Monitoring | `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_AUTH_TOKEN` | The Sentry token is optional and used at build time only. |
| FastAPI base URL *(lands with KAN-113)* | `BACKEND_API_URL` | Not yet in `.env.example`; lands with the FastAPI integration work. Read by `npm run foundation:check`. The server-only API client (KAN-33) reads the same name. |
| FastAPI service key | `BACKEND_INTERNAL_KEY` | Not yet in `.env.example`; lands with the FastAPI integration work. Server-only. Will be sent to FastAPI as the `X-Internal-Key` header (ADR-003). |
| E2E test accounts *(lands with KAN-113)* | `TEST_USER_EMAIL`, `TEST_USER_PASSWORD`, `TEST_ADMIN_EMAIL`, `TEST_ADMIN_PASSWORD` | Written to `.env.e2e.local` by `npm run test:setup`. Do not edit these by hand. The same file also holds the Firebase TEST project config and its `FIREBASE_ADMIN_*` service account; see [testing.md](testing.md#dedicated-firebase-test-project). |

### Build the frontend

```bash
npx prisma generate
npm run build
```

- The build needs the `NEXT_PUBLIC_*` client config in `.env`.
- Until KAN-140 lands, it also needs `DATABASE_URL`.
- It does not need `FIREBASE_ADMIN_*`. Since KAN-136, `firebase-admin` initialises on first use (`src/lib/firebase/admin.ts`).

### Run the frontend

```bash
npm run dev
```

The app serves at `http://localhost:3000`. The `predev` hook runs `scripts/dev-clean.cjs` first. If a stale lock or process blocks startup, run `npm run dev:kill` and then `npm run dev`.

## Backend (`fastapi_backend/`)

```bash
cd fastapi_backend
uv sync
cp .env.example .env   # then set DATABASE_URL (see Local databases)
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000 --reload
```

Run commands from `fastapi_backend/`. `app/core/config.py` reads `.env` from the working directory. Check it with `curl http://localhost:8000/health` (`{"status":"ok"}`); `/health/ready` also queries the database and returns 503 when it is unreachable.

### Backend environment

| Variable names | Required | Notes |
|---|---|---|
| `DATABASE_URL` | Yes | Platform database. |
| `CORS_ORIGINS` | Yes | Set it to `[]`. The browser never calls FastAPI, so no browser origin is allowed (ADR-003). |
| `APP_NAME`, `APP_VERSION`, `LOG_LEVEL`, `OPENAPI_URL`, `EXPIRE_ON_COMMIT` | No | Defaults: `StoreCart API`, `0.1.0`, `INFO`, `/openapi.json`, `false`. |
| `OPENAPI_OUTPUT_FILE` | No | Output path for `commands.generate_openapi_schema`. |

The template's fastapi-users secrets (`ACCESS_SECRET_KEY` and the other two), `TEST_DATABASE_URL`, `FRONTEND_URL` and the `MAIL_*` settings were removed in KAN-30. Email will come back through Resend ([ADR-009](../adr/0009-email-with-resend.md)).

### Run the backend

FastAPI serves on `http://localhost:8000`, with FastAPI's default `/docs` page.

`./start.sh` runs the API together with `watcher.py`, which regenerates the OpenAPI file. On Windows, run it from Git Bash. To regenerate the OpenAPI file once:

```bash
uv run python -m commands.generate_openapi_schema
```

It writes to the path in `OPENAPI_OUTPUT_FILE`.

## Troubleshooting

- **Stuck dev server or `.next/dev/lock` error:** run `npm run dev:kill`, then `npm run dev`.
- **`Module not found` after switching package manager:** this project uses npm only. Delete `node_modules` and run `npm ci`.
- **`Can't reach database server`:** check `DATABASE_URL` in `.env`, that Postgres is running, and the port (see [Local databases](#local-databases)).
- **Prisma client out of date after a schema change:** run `npm run db:generate`, then `npm run db:push` (development) or `npm run db:migrate`.
- **`Firebase: Error (auth/invalid-api-key)`:** the `NEXT_PUBLIC_FIREBASE_*` values must match the Firebase console, and Email/Password sign-in must be enabled there.
- **Stripe webhook signature failures locally:** run `stripe listen --forward-to localhost:3000/api/webhooks/stripe` and set `STRIPE_WEBHOOK_SECRET` to the secret it prints.
- **Admin pages deny access:** the user needs an `AdminUser` record (`node scripts/create-admin.mjs <email>`).

## Pre-commit hooks

The repository root has a `.pre-commit-config.yaml` (KAN-111). It runs ruff, ruff format and mypy on `fastapi_backend/`, and ESLint, Prettier and `tsc --noEmit` on `nextjs-frontend/`. Install it once per clone, after both apps are set up:

```bash
uvx pre-commit install
```

The root [README](../../README.md#-pre-commit-hooks) has the details. There is no CI yet; it lands with KAN-27.

## Running both apps

Run the frontend on port 3000 and the backend on port 8000. On `main`, the frontend does not call FastAPI yet. Wiring happens in KAN-33, after which the Next.js server reads `BACKEND_API_URL`. The browser never calls port 8000 directly ([ADR-003](../adr/0003-nextjs-to-fastapi-authentication.md)).

**Running both together like Vercel does:** from the repository root, `vercel dev -L` starts both services from the root `vercel.json` and injects `BACKEND_API_URL` (the service binding) automatically ([ADR-011](../adr/0011-single-vercel-project-with-services.md)). When you run the apps separately instead, set `BACKEND_API_URL=http://127.0.0.1:8000` in `nextjs-frontend/.env.local`. On Vercel the binding sets it; never set it by hand there. The binding is not available in `src/proxy.ts` or during `next build`.

Next steps: [testing.md](testing.md) for the test commands, [architecture.md](architecture.md) for the request flow.
