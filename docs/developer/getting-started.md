# Getting started

**Last updated:** 2026-10-11

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 22 | Team standard. `nextjs-frontend/package.json` still declares `engines.node >=20`; see [known-issues](known-issues.md). |
| npm | 10 or later | npm only. Do not use pnpm or yarn. |
| Python | 3.12 | Required by `fastapi_backend/pyproject.toml` (`>=3.12,<3.13`). |
| uv | current | Manages the backend environment and dependencies. |
| PostgreSQL | reachable instance | A local server, or a development database. |

Docker is optional. `fastapi_backend/Dockerfile` exists, but there is no `docker-compose.yml` yet.

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

`npm ci` does not generate the Prisma client. Run `npm run db:generate` before `npm run typecheck`, otherwise typecheck fails on missing Prisma types. Run it again after any change to `prisma/schema.prisma`.

### Frontend environment

```bash
cp .env.example .env
```

Fill in the values from the team's secret store. Never commit `.env`. The list below gives names only; `nextjs-frontend/.env.example` is the reference.

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
| FastAPI base URL *(lands with KAN-113)* | `BACKEND_API_URL` | Read by `npm run foundation:check`. The server-only API client (KAN-33) reads the same name. |
| FastAPI service key | `BACKEND_INTERNAL_KEY` | Server-only. Sent to FastAPI as the `X-Internal-Key` header. |
| E2E test accounts *(lands with KAN-113)* | `TEST_USER_EMAIL`, `TEST_USER_PASSWORD`, `TEST_ADMIN_EMAIL`, `TEST_ADMIN_PASSWORD` | Written to `.env.e2e.local` by `npm run test:setup`. Do not edit by hand. |

### Run the frontend

```bash
npm run dev
```

The app serves at `http://localhost:3000`. The `predev` hook runs `scripts/dev-clean.cjs` first. If a stale lock or process blocks startup, run `npm run dev:kill` and then `npm run dev`.

## Backend (`fastapi_backend/`)

```bash
cd fastapi_backend
uv sync
cp .env.example .env
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000 --reload
```

Run commands from `fastapi_backend/`. `app/config.py` reads `.env` from the working directory.

### Backend environment

| Variable names | Required | Notes |
|---|---|---|
| `DATABASE_URL` | Yes | Platform database. |
| `CORS_ORIGINS` | Yes | Set it to `[]`. The browser never calls FastAPI, so no browser origin is allowed (ADR-003). |
| `ACCESS_SECRET_KEY`, `RESET_PASSWORD_SECRET_KEY`, `VERIFICATION_SECRET_KEY` | Yes | Template fastapi-users secrets. Removed in KAN-30 (template adaptation). |
| `TEST_DATABASE_URL` | For `pytest` | Used by `tests/conftest.py`. |
| `FRONTEND_URL`, `OPENAPI_OUTPUT_FILE` | No | `FRONTEND_URL` defaults to `http://localhost:3000`. |
| `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_SERVER`, `MAIL_PORT`, `MAIL_STARTTLS`, `MAIL_SSL_TLS`, `USE_CREDENTIALS` | No | Template fastapi-mail settings. Replaced by Resend ([ADR-009](../adr/0009-email-with-resend.md)). |

### Run the backend

FastAPI serves on `http://localhost:8000`, with FastAPI's default `/docs` page.

`./start.sh` runs the API together with `watcher.py`, which regenerates the OpenAPI file. On Windows, run it from Git Bash. To regenerate the OpenAPI file once:

```bash
uv run python -m commands.generate_openapi_schema
```

It writes to the path in `OPENAPI_OUTPUT_FILE`.

## Running both apps

Run the frontend on port 3000 and the backend on port 8000. On `main`, the frontend does not call FastAPI yet. Wiring happens in KAN-33, after which the Next.js server reads `BACKEND_API_URL`. The browser never calls port 8000 directly ([ADR-003](../adr/0003-nextjs-to-fastapi-authentication.md)).

Next steps: [testing.md](testing.md) for the test commands, [architecture.md](architecture.md) for the request flow.
