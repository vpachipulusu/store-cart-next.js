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
- Local runs create the accounts in whichever Firebase project your `.env` points at; see [security.md](security.md).
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
