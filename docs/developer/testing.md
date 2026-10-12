# Testing

**Last updated:** 2026-10-12

Coverage target: **80%** minimum. Write the test first (RED), make it pass (GREEN), then refactor.

## Frontend unit tests (Vitest)

```bash
cd nextjs-frontend
npm run test:unit          # src/__tests__/unit
npm run test:watch         # watch mode
npm run test:coverage      # enforces the 80% thresholds; currently FAILS (see below)
```

- Config: `vitest.config.ts`. Environment is jsdom, setup file is `vitest.setup.ts`.
- Coverage thresholds are 80% for branches, functions, lines and statements.
- **`npm run test:coverage` currently fails.** Coverage is about 2% lines, 3% functions and 10% branches. Whether and how the 80% rule applies is a PO decision tracked in KAN-139.
- Coverage counts `src/lib/**`, `src/components/**` and `src/app/actions/**`.
- Vitest excludes `e2e/` and `*.spec.ts`.
- MSW is available for mocking HTTP.

## Frontend integration tests (Vitest)

```bash
npm run test:integration   # src/__tests__/integration
```

There is currently one placeholder: `src/__tests__/integration/api/health.test.ts`, which asserts on a local object. No integration test exercises an API endpoint or a database yet.

## Frontend end-to-end tests (Playwright)

```bash
npm run test:e2e                              # all projects in playwright.config.ts
npx playwright test --project=chromium        # the Chromium baseline
npm run test:e2e:ui                           # interactive UI mode
npm run test:e2e:subscription                 # subscription specs only
npm run test:all                              # Vitest and Playwright together
```

- Tests live in `nextjs-frontend/src/__tests__/e2e/`. `auth.setup.ts` runs first, and the browser projects depend on it.
- Chromium is the baseline. The foundation check runs only that project.
- Playwright starts `npm run dev` on `http://localhost:3000` itself. Locally it reuses a server already on that port. With `CI` set, it always starts a fresh one. Stop any dev server pointed at another backend before a run.

### Test accounts

- `npm run test:setup` creates the test accounts. On `main`, it runs `scripts/create-test-user.mjs`.
- *(lands with KAN-113)* `npm run test:setup` runs `scripts/setup-e2e-accounts.mjs` instead. It:
  - creates one e2e user and one admin, with random emails and passwords;
  - writes `.env.e2e.local`, which is gitignored and loaded by `playwright.config.ts`;
  - refuses a `DATABASE_URL` whose host is not `localhost`, `127.0.0.1`, `::1` or `db`;
  - never prints credentials.
- Re-running `npm run test:setup` reuses the stored credentials and resets the Firebase passwords to match.
- `npm run test:reset` resets the test user. The script exists on `main`. Its behaviour with the new accounts has not been reviewed.
- The accounts live in the Firebase project that production will use until KAN-131 moves them. See [security.md](security.md).

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
uv run mypy .
```

- `uv run mypy .` reports existing errors (80 at the last verification; template code, KAN-30). Do not add new ones.
- A bare `uv run mypy` also works: `mypy.ini` sets `files = app, commands`.

## OpenAPI check

After changing a backend route, regenerate the schema:

```bash
cd fastapi_backend
uv run python -m commands.generate_openapi_schema
```

CI is planned to fail when the generated client is stale (ADR-008, lands with KAN-27).

## Before you open a PR

- Frontend: `npm run test:unit`, `npm run test:integration`, `npm run typecheck`, `npm run lint` and `npm run build`.
- Frontend coverage: do not let it drop. The global 80% gate is not required until KAN-139 is decided.
- Backend: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy .` with no new errors.
- Chromium e2e when the change is user-facing.
