# Getting started

**Last updated:** 2026-10-12

## Prerequisites

| Tool       | Version                   | Notes                                                                                            |
| ---------- | ------------------------- | ------------------------------------------------------------------------------------------------ | --- | --------- |
| Node.js    | 22.12 or later (22 or 24) | Team standard. `nextjs-frontend/package.json` declares `engines.node ^22.12.0                    |     | ^24.0.0`. |
| npm        | 10 or later               | npm only. Do not use pnpm or yarn.                                                               |
| Python     | 3.12                      | Required by `fastapi_backend/pyproject.toml` (`>=3.12,<3.13`).                                   |
| uv         | current (CI uses 0.8.12)  | Manages the backend environment and dependencies.                                                |
| PostgreSQL | reachable instance        | A local server on port 5432, or a development database. See [Local databases](#local-databases). |

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

Most backend tests need no database (they use fake sessions). The real-route e2e tests run only when `TEST_DATABASE_URL` points at a local throwaway `*_test` database; see [testing.md](testing.md#backend-tests-pytest).

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
npm run typecheck
```

### Frontend environment

```bash
cp .env.example .env
```

Fill in the values from the team's secret store. Never commit `.env`. The list below gives names only. `nextjs-frontend/.env.example` is the reference for the variables `main` uses today; rows marked "not yet in `.env.example`" are planned.

| Group                                    | Variable names                                                                                                                                                                                                             | Notes                                                                                                                                                                                                                                                                                                            |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Database                                 | `DATABASE_URL`                                                                                                                                                                                                             | Server-only. Must leave the frontend in KAN-51 (E6).                                                                                                                                                                                                                                                             |
| Firebase client                          | `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`, `NEXT_PUBLIC_FIREBASE_PROJECT_ID`, `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`, `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`, `NEXT_PUBLIC_FIREBASE_APP_ID`    | Public by design.                                                                                                                                                                                                                                                                                                |
| Firebase Admin                           | `FIREBASE_ADMIN_PROJECT_ID`, `FIREBASE_ADMIN_CLIENT_EMAIL`, `FIREBASE_ADMIN_PRIVATE_KEY`                                                                                                                                   | Server-only. Must leave the frontend in KAN-51.                                                                                                                                                                                                                                                                  |
| Stripe                                   | `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_PRO_MONTHLY`, `STRIPE_PRICE_ID_PRO_YEARLY`, `STRIPE_PRICE_ID_ENTERPRISE_MONTHLY`, `STRIPE_PRICE_ID_ENTERPRISE_YEARLY` | Secret keys are server-only. Checkout and the pricing page read the `_MONTHLY`/`_YEARLY` names (preferred). `STRIPE_PRICE_ID_FREE`, `STRIPE_PRICE_ID_PRO` and `STRIPE_PRICE_ID_ENTERPRISE` are legacy names the frontend no longer reads. A wrong price ID name shows up only as a broken checkout after deploy. |
| Cloudflare R2 (backend, optional)        | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_BASE_URL` | Set all five or none (a partial set refuses to start). Unset means the image upload route answers 503. See [backend media](backend-media.md). |
| Email                                    | `RESEND_API_KEY`                                                                                                                                                                                                           | Not read by any frontend code today (KAN-143), so it is no longer in `.env.example`. Email lives in the backend ([ADR-009](../adr/0009-email-with-resend.md)).                                                                                                                                                   |
| Auth                                     | `NEXTAUTH_SECRET`                                                                                                                                                                                                          | Not read by any frontend code today (KAN-143), so it is no longer in `.env.example`.                                                                                                                                                                                                                             |
| App                                      | `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_APP_NAME`, `APP_ID`, `APP_NAME`, `NODE_ENV`, `LOG_LEVEL`                                                                                                                               |                                                                                                                                                                                                                                                                                                                  |
| Monitoring                               | `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_AUTH_TOKEN`                                                                                                                                                                              | The Sentry token is optional and used at build time only.                                                                                                                                                                                                                                                        |
| FastAPI base URL _(lands with KAN-113)_  | `BACKEND_API_URL`                                                                                                                                                                                                          | Not yet in `.env.example`; lands with the FastAPI integration work. Read by `npm run foundation:check`. The server-only API client (KAN-33) reads the same name.                                                                                                                                                 |
| FastAPI service key                      | `BACKEND_INTERNAL_KEY`                                                                                                                                                                                                     | Server-only. Read by `src/lib/api/server.ts`; in `.env.example`. Sent to FastAPI as the `X-Internal-Key` header (ADR-003).                                                                                                                                                                                       |
| Backend TOTP encryption                  | `TOTP_ENCRYPTION_KEY`                                                                                                                                                                                                      | Optional backend-only Fernet key. TOTP routes fail closed with 503 when unset; invalid configured keys prevent startup. Preserve the key across deployments; see [backend TOTP](backend-totp.md).                                                                                                                |
| E2E test accounts _(lands with KAN-113)_ | `TEST_USER_EMAIL`, `TEST_USER_PASSWORD`, `TEST_ADMIN_EMAIL`, `TEST_ADMIN_PASSWORD`                                                                                                                                         | Written to `.env.e2e.local` by `npm run test:setup`. Do not edit these by hand. The same file also holds the Firebase TEST project config and its `FIREBASE_ADMIN_*` service account; see [testing.md](testing.md#dedicated-firebase-test-project).                                                              |

Stripe checkout and billing-portal return URLs are built on the server from `NEXT_PUBLIC_APP_URL` (KAN-127): in production it is required (a missing or malformed value throws), on Vercel previews it falls back to `https://$VERCEL_URL`, and locally to `http://localhost:3000`. It must match the real deployment host (`www` vs apex, previews), otherwise users return to the wrong host and the host-scoped `checkout_token` cookie check fails.

### Build the frontend

```bash
npm run build
```

- The build needs the `NEXT_PUBLIC_*` client config in `.env`.
- Since KAN-140 it does not need `DATABASE_URL`: DB-backed routes render dynamically and the root layout falls back to defaults when no database is configured.
- **CI and image builds must leave `DATABASE_URL` unset.** Do not copy `.env.example` into a CI build. `isDatabaseConfigured()` in `src/lib/db/config.ts` returns true for any non-blank `DATABASE_URL` (it only checks `process.env.DATABASE_URL?.trim()`), so the placeholder in `.env.example` counts as configured and prerendering would try a query against a database that is not there. Set only the `NEXT_PUBLIC_*` placeholders, as `.github/workflows/frontend.yml` does.
- It does not need `FIREBASE_ADMIN_*`, `STRIPE_SECRET_KEY` or any other server secret: the frontend has no `firebase-admin` or `stripe` dependency (KAN-208). Sessions, ID tokens, password changes and plan prices go through the backend.

### Run the frontend

```bash
npm run dev
```

The app serves at `http://localhost:3000` (set `PORT` to change it; see [Running in parallel](#running-in-parallel)). The `predev` hook runs `scripts/dev-clean.cjs` first. If a stale lock or process blocks startup, run `npm run dev:kill` and then `npm run dev`.

## Backend (`fastapi_backend/`)

```bash
cd fastapi_backend
uv sync
cp .env.example .env   # then set DATABASE_URL (see Local databases)
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000 --reload   # --port $BACKEND_PORT to move it
```

Run commands from `fastapi_backend/`. `app/core/config.py` reads `.env` from the working directory. Check it with `curl http://localhost:8000/health` (`{"status":"ok"}`); `/health/ready` also queries the database and returns 503 when it is unreachable.

### Backend environment

| Variable names                                                            | Required | Notes                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                                                            | Yes      | Platform database.                                                                                                                                                                                                                                                                     |
| `DATABASE_URL_DIRECT`                                                     | No       | Neon unpooled endpoint. `alembic` uses it when set, else `DATABASE_URL` (ADR-005). `sslmode` is passed to asyncpg as `ssl`.                                                                                                                                                            |
| `APP_NAME`, `APP_VERSION`, `LOG_LEVEL`, `OPENAPI_URL`, `EXPIRE_ON_COMMIT` | No       | Defaults: `StoreCart API`, `0.1.0`, `INFO`, `/openapi.json`, `false`.                                                                                                                                                                                                                  |
| `SENTRY_DSN`                                                              | No       | Backend error reporting (KAN-35). Unset locally and in tests: Sentry then stays off. Set in deployed environments. Environment comes from `VERCEL_ENV` (else `ENVIRONMENT`), release from `VERCEL_GIT_COMMIT_SHA`. See [`fastapi_backend/CLAUDE.md`](../../fastapi_backend/CLAUDE.md). |
| `OPENAPI_OUTPUT_FILE`                                                     | No       | Output path for `commands.generate_openapi_schema`. Default: `nextjs-frontend/openapi.json`.                                                                                                                                                                                           |

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
- **`Can't reach database server`:** check the backend `DATABASE_URL`, that Postgres is running, and the port (see [Local databases](#local-databases)).
- **`Firebase: Error (auth/invalid-api-key)`:** the `NEXT_PUBLIC_FIREBASE_*` values must match the Firebase console, and Email/Password sign-in must be enabled there.
- **Stripe webhook signature failures locally:** run `stripe listen --forward-to localhost:8000/webhooks/stripe` (the FastAPI backend; use its port if you changed it) and set `STRIPE_WEBHOOK_SECRET` to the secret it prints.
- **Admin pages deny access:** the user needs an admin grant in the backend (`POST /v1/admin/users/{user_id}/admin` from an existing admin, or the SQL in [local-e2e.md](local-e2e.md)).

## Pre-commit hooks

The repository root has a `.pre-commit-config.yaml` (KAN-111). It runs ruff, ruff format and mypy on `fastapi_backend/`, and ESLint, Prettier and `tsc --noEmit` on `nextjs-frontend/`. Install it once per clone, after both apps are set up:

```bash
uvx pre-commit install
```

The root [README](../../README.md#-pre-commit-hooks) has the details. There is no CI yet; it lands with KAN-27.

## Running both apps

Run the frontend on port 3000 and the backend on port 8000 (the defaults; both can be changed, see [Running in parallel](#running-in-parallel)). On `main`, the frontend does not call FastAPI yet. Wiring happens in KAN-33, after which the Next.js server reads `BACKEND_API_URL`. The browser never calls port 8000 directly ([ADR-003](../adr/0003-nextjs-to-fastapi-authentication.md)).

**Running both together like Vercel does:** from the repository root, `vercel dev -L` starts both services from the root `vercel.json` and injects `BACKEND_API_URL` (the service binding) automatically ([ADR-011](../adr/0011-single-vercel-project-with-services.md)). When you run the apps separately instead, set `BACKEND_API_URL=http://127.0.0.1:8000` in `nextjs-frontend/.env.local`. On Vercel the binding sets it; never set it by hand there. The binding is not available in `src/proxy.ts` or during `next build`.

## Running in parallel

Two checkouts (for example two git worktrees) can run side by side when each uses its own ports (KAN-167). The defaults are unchanged, and CI and Vercel set none of these variables.

| Variable                                        | Default                                   | What it moves                                                                                                 |
| ----------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `PORT`                                          | `3000`                                    | `npm run dev`, `npm start`, `npm run dev:kill` (kills only the listener on exactly this port)                 |
| `E2E_PORT`                                      | `3000`                                    | The Playwright-managed server, `baseURL`, and the e2e build (`NEXT_PUBLIC_APP_URL` is baked in at build time) |
| `BACKEND_PORT`                                  | `8000`                                    | `fastapi_backend/start.sh`, and the e2e server's `BACKEND_API_URL` (`http://127.0.0.1:$BACKEND_PORT`)         |
| `BACKEND_API_URL`                               | unset                                     | Wins over `BACKEND_PORT` when set explicitly                                                                  |
| `COMPOSE_PROJECT_NAME`, `*_PORT` in root `.env` | `storecart`, 5432, 5434, 6379, 8000, 3000 | Docker stack: separate containers and volumes, other host ports (container ports do not change)               |

Example, second checkout next to one on the defaults:

```bash
# fastapi_backend/ (terminal 1)
BACKEND_PORT=8100 ./start.sh

# nextjs-frontend/ (terminal 2): dev server
PORT=3100 BACKEND_API_URL=http://127.0.0.1:8100 npm run dev

# nextjs-frontend/: e2e (the build records its port; a build for another E2E_PORT is refused)
E2E_PORT=3100 BACKEND_PORT=8100 npm run test:e2e:build
E2E_PORT=3100 BACKEND_PORT=8100 npx playwright test --config=playwright.baseline.config.ts dashboard
```

Rebuild with `npm run test:e2e:build` whenever you change `E2E_PORT`. Each checkout has its own `.next-e2e` folder, so builds do not collide. Use `PORT=3100 npm run dev:kill` to stop only that checkout's dev server. Database and Firebase test project are shared unless you point each checkout's `.env.e2e.local` at its own; avoid running the same specs against one database from both checkouts at once.

Next steps: [testing.md](testing.md) for the test commands, [architecture.md](architecture.md) for the request flow.
