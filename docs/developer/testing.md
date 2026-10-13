# Testing

**Last updated:** 2026-10-12

Coverage target: **80%** minimum. Write the test first (RED), make it pass (GREEN), then refactor.

## Frontend unit tests (Vitest)

```bash
cd nextjs-frontend
npm run test:unit          # src/__tests__/unit
npm run test:watch         # watch mode
npm run test:coverage      # enforces the coverage ratchet (see below)
```

- Config: `vitest.config.ts`. Environment is jsdom, setup file is `vitest.setup.ts`.
- **Coverage ratchet (KAN-27, PO decision on KAN-139).** The thresholds in `vitest.config.ts` are the measured baseline (2026-10-12: 5.07% lines and statements, 6.33% functions, 29.87% branches). CI fails if coverage drops below them. Raise them towards 80% as tests are added and never lower them. To set them to the current values in one step, run `COVERAGE_RATCHET=1 npm run test:coverage`, then run `npx prettier --write vitest.config.ts` (Vitest rewrites the file without Prettier formatting) and commit the config.
- Coverage counts `src/lib/**`, `src/components/**` and `src/app/actions/**`.
- Vitest excludes `e2e/` and `*.spec.ts`.
- MSW is available for mocking HTTP.

## Frontend integration tests (Vitest)

```bash
npm run test:integration   # src/__tests__/integration
```

There are currently no integration tests, and the `src/__tests__/integration` folder does not exist (KAN-146 removed the only placeholder, which asserted on a local object). Running the script now finds no directory. Add the folder with the first real test that exercises an API endpoint or a database.

## Frontend end-to-end tests (Playwright)

```bash
npm run test:e2e:db                # once: apply the Prisma schema to the dedicated e2e database
npm run test:setup                 # once: create the e2e user and admin in the TEST Firebase project and e2e database
npm run test:e2e:build             # build the e2e app once (.next-e2e, test Firebase project, Sentry off)
npm run test:e2e:baseline          # the gated Chromium baseline against that build (never builds)
npm run test:e2e:baseline:build    # both of the above
npm run test:e2e                   # all projects in playwright.config.ts, against `npm run dev`
npm run test:e2e:ui                # interactive UI mode
```

- Tests live in `nextjs-frontend/src/__tests__/e2e/`. `auth.setup.ts` runs first, and the browser projects depend on it.
- **The baseline gate** (`playwright.baseline.config.ts`, PO-approved scope) is Chromium only and runs the specs for the flows Foundation keeps: auth, session-expiry, dashboard, subscription, subscription-simple, billing-management and admin. homepage, currency and pricing specs stay in the repo outside the gate. It uses 4 workers locally and 1 in CI.
- Specs import `test` and `expect` from `helpers/fixtures.ts`, not from `@playwright/test`.

### Dedicated Firebase test project and test database

e2e runs against the Firebase TEST project **`storecart-test`** and a **dedicated Postgres test database**, never the dev project or dev database in `.env.local`/`.env`. **The dev and test environments must never be mixed:** the scripts refuse to run when the e2e config is missing, names the dev project, pairs a service account from one project with the web config of another, or when the e2e `DATABASE_URL` is missing or equals the dev one (they compare the parsed values and print only "same"/"different" or the host).

- All e2e config lives in `nextjs-frontend/.env.e2e.local` (gitignored). `scripts/e2e-env.cjs` merges it over `.env.local` and `.env` for e2e only. The Firebase variables and `DATABASE_URL` are taken only from `.env.e2e.local` or real environment variables (CI), never from `.env`/`.env.local`. Your normal `.env.local` stays untouched.
- `.env.e2e.local` holds:
  - the test project's public web config: `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`, `NEXT_PUBLIC_FIREBASE_PROJECT_ID`, `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`, `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`, `NEXT_PUBLIC_FIREBASE_APP_ID`;
  - the test project's service account, which **the project owner adds by hand**: `FIREBASE_ADMIN_PROJECT_ID`, `FIREBASE_ADMIN_CLIENT_EMAIL`, `FIREBASE_ADMIN_PRIVATE_KEY` (Firebase Console > Project settings > Service accounts > Generate new private key, for `storecart-test`). Never paste these into chat, tickets or commits;
  - `DATABASE_URL`, the dedicated e2e test database, added by the project owner (never the dev database);
  - the e2e accounts, written by `npm run test:setup`: `TEST_USER_EMAIL`, `TEST_USER_PASSWORD`, `TEST_ADMIN_EMAIL`, `TEST_ADMIN_PASSWORD`.
- In the test project, Firebase Console > Authentication > Sign-in method must have **Email/Password** enabled. `auth.setup.ts` fails with a clear message if it is not.
- `npm run test:setup`, `auth.setup.ts` and `scripts/e2e-start.mjs` fail fast and name the missing variables. They never print values.
- `npm run test:e2e:db` (`scripts/e2e-db.mjs`) applies the Prisma schema (`prisma db push`; the repo has no migrations) to the e2e database, using the e2e env only. Plain `npm run db:push` uses `.env`, i.e. the dev database; do not use it for e2e.

### Separate e2e build

`NEXT_PUBLIC_*` values are baked in at build time, so the e2e build must be separate from your normal local build:

- `npm run test:e2e:build` builds into **`.next-e2e`** (not `.next`) with the test project's config and an empty `NEXT_PUBLIC_SENTRY_DSN` (Sentry off). It writes `.next-e2e/e2e-build.json` with the Firebase project id.
- The baseline's webServer runs `scripts/e2e-start.mjs`, which only serves. It refuses to start when there is no e2e build, when the build's project id differs from the current e2e env, or when the build had Sentry on. It warns when the build is from another commit.
- Playwright reuses a server already on port 3000 only with `E2E_REUSE_SERVER=1`, so a normal dev server (dev project) is never tested by accident. To keep one running between runs, start it with `node scripts/e2e-start.mjs`.
- CI builds in its own step (`npm run test:e2e:build`), then runs `npm run test:e2e:baseline` (KAN-27).
- `npm run test:e2e` (the full config) starts `npm run dev` with the e2e env and its own output folder `.next-e2e-dev`.

### Logins, sessions and test accounts

- `auth.setup.ts` logs in through the UI **once per role** (`user`, `admin`) and saves the session cookies to `playwright/.auth/<role>.json` (gitignored). Read-only specs use `test.use({ storageState: STORAGE_STATE.<role> })`, or `signInWithSavedSession(context, role)` for one test in an otherwise logged-out describe.
- `loginViaUI` stays only where the login itself is under test, and for throwaway accounts.
- **Isolation:** a test that logs out, revokes or expires a session, or changes plan or billing state (Stripe checkout, auto-renewal) must use the `throwawayAccount` fixture: a fresh free-tier account created in the test project and the e2e database, logged in with `loginAsThrowawayAccount`, and deleted after the test. Firebase revokes sessions per user, not per cookie, so one such test on a shared role account would break every other worker's saved session.
- No `networkidle` waits. Firebase, Stripe and Sentry keep connections open, so `networkidle` can time out on its own. `waitForPageReady` waits for `load` and React hydration. Use web-first assertions, `waitForURL`, or `waitForServerActionResponse`.
- Every browser context blocks `*.sentry.io` (in `helpers/fixtures.ts`), in addition to the Sentry-off build.

### Test accounts

- `npm run test:setup` runs `scripts/setup-e2e-accounts.mjs`. It:
  - creates one e2e user and one admin in the **test** Firebase project through the Admin SDK, using the e2e env only;
  - updates only the `TEST_*` keys in `.env.e2e.local` and keeps everything else;
  - creates their `users` rows (free tier, no Stripe links, reset on every run) and the admin's `AdminUser` row in the e2e database, and refuses a missing `DATABASE_URL` or one equal to the dev database;
  - never prints credentials.
- Re-running `npm run test:setup` reuses the stored credentials and resets the Firebase passwords to match.
- `npm run test:reset` (`scripts/reset-test-user.mjs`) is not part of the e2e flow and does not use the e2e env.
- Accounts created before KAN-113 moved e2e to `storecart-test` still exist in the dev project. KAN-131 deletes them.
- CI e2e uses only the dedicated Firebase test project `storecart-test` (GitHub environment `e2e-test`) and Stripe test-mode keys. It must never use the development or production projects: the e2e job refuses live Stripe keys and refuses to run when `E2E_FIREBASE_PROJECT_ID` equals the repository variable `PROD_FIREBASE_PROJECT_ID`.

### Assertion rule

Update an assertion only when user-visible behaviour is unchanged, for example a selector that moved in a refactor. If the behaviour itself must change, raise it on the Jira story. Do not edit the assertion to match.

## Foundation check *(lands with KAN-113)*

```bash
BACKEND_API_URL=http://localhost:8000 npm run foundation:check
```

The check (`scripts/foundation-done-check.cli.ts`) does three things:

1. Scans every git-tracked and untracked, non-ignored text file under `nextjs-frontend/`. It flags references to `DATABASE_URL`, Firebase Admin, Stripe and Resend secrets, Prisma and `firebase-admin` imports, dynamic `process.env` reads, committed env files other than `.env.example`, and server-only dependencies in `package.json`.
2. Requires `BACKEND_API_URL`, then checks `GET {BACKEND_API_URL}/health` (the backend has no `/health` route yet).
3. Runs the Chromium e2e suite with `CI=1` against FastAPI.

It fails until KAN-51 (E6.1) removes the last server secrets and database access. The failure is expected until then.

## Backend tests (pytest)

```bash
cd fastapi_backend
uv run pytest
```

- Config: `pytest.ini` sets `asyncio_mode = auto`.
- Tests live in `fastapi_backend/tests/`. `conftest.py` builds its engine from `TEST_DATABASE_URL`.
- pytest imports `app.config`, so `.env` must set `DATABASE_URL`, `ACCESS_SECRET_KEY`, `RESET_PASSWORD_SECRET_KEY`, `VERIFICATION_SECRET_KEY` and `CORS_ORIGINS`, and `TEST_DATABASE_URL` must point at a reachable test database. Without them pytest exits with code 4 at import. Run `cp .env.example .env` and edit the two URLs (the example's test port 5433 is wrong here; see [getting-started](getting-started.md#local-databases)).

Lint and types, using the dev-group tools:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

- A bare `uv run mypy` checks `app` and `commands` (`mypy.ini` sets `files = app, commands`), the same scope as the pre-commit hook.
- It reports existing errors: 31 on 2026-10-12, from template code (KAN-30). Do not add new ones. `fastapi_backend/mypy-baseline.txt` holds the expected count and CI fails when the count differs from it: higher means new errors, lower means you must lower the baseline to the new count in the same PR. CI also fails if mypy crashes, exits 1 without reporting errors, or the baseline file is empty or not a number.
- Coverage: `uv run pytest --cov`. `fail_under` in `[tool.coverage.report]` of `pyproject.toml` is the backend ratchet (baseline 84.13% lines of `app` and `commands` on 2026-10-12): raise it, never lower it.
- Frontend lint: `npm run lint` runs `eslint .` with the flat config `eslint.config.mjs` (fixed in KAN-111).

## OpenAPI check

After changing a backend route, regenerate the schema:

```bash
cd fastapi_backend
uv run python -m commands.generate_openapi_schema
```

CI runs the pre-commit `openapi-schema-check` hook on changed backend files. Failing on a stale generated client (ADR-008) arrives with KAN-33, which commits the schema and client.

## Continuous integration (KAN-27)

`.github/workflows/ci.yml` runs on every pull request to `main` and every push to `main`:

| Job | Runs when | Checks |
|---|---|---|
| Detect changed paths | always | `dorny/paths-filter` decides frontend / backend |
| Pre-commit (changed files) | pull requests | `pre-commit run --from-ref origin/<base> --to-ref HEAD` |
| Frontend (`frontend.yml`) | `nextjs-frontend/**` or shared config | lint, typecheck, Vitest with coverage ratchet, `npm run build` with placeholder `NEXT_PUBLIC_*` only |
| Backend (`backend.yml`) | `fastapi_backend/**` or shared config | ruff lint and format, mypy against baseline, pytest with coverage ratchet (Postgres service) |
| E2E (`e2e.yml`) | frontend changed and repo variable `E2E_ENABLED=true` | Chromium Playwright, secrets from environment `e2e-test`. Not in the gate until KAN-113 |
| **CI gate** | always | passes when every job above (except E2E) succeeded or was skipped |

Shared config is `.github/**`, `.pre-commit-config.yaml`, root `package.json` / `package-lock.json`, `vercel.json` and the OpenAPI schema `nextjs-frontend/openapi.json`; it triggers both apps. A manual run (`workflow_dispatch`) runs both apps. The E2E job also runs only for pull requests from this repository, not from forks. Actions are SHA-pinned and kept current by Dependabot (`.github/dependabot.yml`, weekly). Branch protection requires only **CI gate**.

## Before you open a PR

- Frontend: `npm run test:unit`, `npm run typecheck`, `npm run lint` and `npm run build`.
- Coverage: do not let it drop below the ratchet; CI enforces it.
- Backend: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy` with no new errors.
- Chromium e2e when the change is user-facing.
