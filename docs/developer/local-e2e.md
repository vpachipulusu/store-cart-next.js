# Running Playwright E2E locally

**Last updated:** 2026-10-14 (KAN-178)

CI skips Playwright (`E2E_ENABLED=false`), so developers run E2E before opening a PR for user-facing changes. This page is the fast path. Test accounts, the test Firebase project and the test database are described in [testing.md](testing.md).

## The command

From `nextjs-frontend/`:

```bash
npm run test:e2e:local -- src/__tests__/e2e/touch-targets.spec.ts src/__tests__/e2e/theme-contrast.spec.ts
```

Everything after `--` goes to Playwright (spec paths, `--grep`, `--headed`, `--workers=2`). With no spec it runs every spec in the chromium project.

What it does, in order (a timing table is printed at the end):

| Step         | What happens                                                                                                                                                                                                                                                                                                                                                                           |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `setup`      | Copies missing `.env`, `.env.local`, `.env.e2e.local` from the main checkout. Links `node_modules` to the main checkout's when `package-lock.json` and `prisma/schema.prisma` are identical, otherwise `npm ci --prefer-offline`. Runs `prisma generate` only when the client is missing or older than the schema. Installs Chromium only if it is not in the global Playwright cache. |
| `build`      | `next build --webpack` into `.next-e2e` (never your `.next`). Skipped when the commit, uncommitted edits, port and `.env.e2e.local` are unchanged since the last build.                                                                                                                                                                                                                |
| `serve+warm` | `next start` on a free port, then requests `/`, `/login`, `/signup`, `/pricing` and `/dashboard` once.                                                                                                                                                                                                                                                                                 |
| `test`       | `playwright.local.config.ts`: chromium plus the auth setup project, up to 4 workers (CPU count / 2).                                                                                                                                                                                                                                                                                   |
| cleanup      | The server process tree is stopped on exit and on Ctrl+C. Server output is in `test-results/e2e-local-server.log`.                                                                                                                                                                                                                                                                     |

Why a production build and not `next dev`: dev compiles each route on first request (40-58 s for `/` and `/login` cold), which broke the one-time login and caused hydration timeouts under parallel workers. A production build has no per-route compile, so warming only primes the server.

## Expected timings

Measured on the dev machine (Windows 11, 4 workers), five specs (button-contrast, motion-hygiene, theme-contrast, display-font, touch-targets; 27 tests):

| Scenario                                                      | Total | Result                                                       |
| ------------------------------------------------------------- | ----- | ------------------------------------------------------------ |
| Before: plain Playwright with a cold `next dev`               | 203 s | 26 passed, 1 failed (hydration timeout)                      |
| Before: `npm ci --prefer-offline` in a new worktree (one-off) | 255 s | removed by the node_modules link                             |
| After: clean worktree, nothing installed or built             | 113 s | 27 passed (setup 4 s, build 73 s, serve+warm 6 s, test 29 s) |
| After: same code, build cached                                | 34 s  | 27 passed (build 0.3 s, serve+warm 4 s, test 28 s)           |

So a clean worktree went from about 4 min of install plus a flaky 3.4 min run to under 2 min, and a repeat run is about 30 s.

## Setup before the first run (KAN-165)

When to run it, and how to report it in the PR, is in [workflow.md](workflow.md#local-e2e-is-required-for-user-facing-changes-kan-165).

**1. `nextjs-frontend/.env.e2e.local`** (gitignored; the script copies it from the main checkout into a worktree). It holds the dedicated Firebase **test** project `storecart-test` (public web config plus the `FIREBASE_ADMIN_*` service account, added by the owner), the dedicated e2e `DATABASE_URL` (legacy Prisma paths; never the dev database), Stripe **test-mode** keys and price ids (`STRIPE_PRICE_ID_PRO_YEARLY` is the discounted yearly test price), and the accounts written by `npm run test:setup` (`TEST_USER_*`, `TEST_ADMIN_*`). Details and the "never mix dev and test" checks are in [testing.md](testing.md#dedicated-firebase-test-project-and-test-database). Never paste values into chat, tickets or commits.

**2. A backend for the app to call.** The frontend only talks to FastAPI, so the specs need your own backend on free ports. Do not reuse another session's container or port.

```bash
# throwaway Postgres 17 on a free port (pick your own)
docker run -d --name my-e2e-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=my_e2e -p 127.0.0.1:55470:5432 postgres:17

cd fastapi_backend
export DATABASE_URL=postgresql+asyncpg://postgres:pw@127.0.0.1:55470/my_e2e ENVIRONMENT=local STORE_DB_PROVIDER=local
export BACKEND_INTERNAL_KEY=<32+ random chars> RATE_LIMIT_EMAIL_KEY=<32+ random chars>
export TOTP_ENCRYPTION_KEY=<a Fernet key>                       # without it the 2FA re-authentication spec gets 503
export BILLING_RETURN_URL_ORIGINS=http://localhost:<E2E port>   # without it checkout fails (the port is printed by the script)
# plus FIREBASE_ADMIN_* and STRIPE_* from .env.e2e.local (the test project, same as the frontend)
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8170
```

In the shell you run the tests from:

```bash
export BACKEND_API_URL=http://127.0.0.1:8170 BACKEND_INTERNAL_KEY=<the same key>
```

The admin specs need an admin grant in the backend database for the `TEST_ADMIN_EMAIL` account. The user row exists only after that account has logged in once (the first run does it), so grant it after the first run and run again:

```bash
docker exec my-e2e-pg psql -U postgres -d my_e2e -c "insert into admin_users(id,user_id,role,permissions) select 'adm_e2e', id, 'super_admin', '[\"*\"]'::jsonb from users where email = '<TEST_ADMIN_EMAIL>' on conflict do nothing"
```

Remove the container when done (`docker rm -f my-e2e-pg`). A spec that fails with a 403 (admin), a 503 (2FA) or a checkout that never opens usually means one of these three settings is missing.

**3. A server you start yourself (optional).** `E2E_REUSE_SERVER=1` makes plain Playwright (`npm run test:e2e`, `test:e2e:baseline`) reuse a server already on `E2E_PORT` instead of starting one, so a normal dev server is never tested by accident. Build with `npm run test:e2e:build`, start it with `node scripts/e2e-start.mjs`. `npm run test:e2e:local` does not need this: it builds, serves and stops its own server.

## Focused specs vs the full run

Measured on `main` 1a4c9e2 (Windows 11, 4 workers), against a fresh throwaway backend:

| What                                                     | Command                                                         | Time                           |
| -------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------ |
| Focused: the spec(s) of the area you changed             | `npm run test:e2e:local -- src/__tests__/e2e/dashboard.spec.ts` | build cached: under 1 min      |
| Four specs (admin, billing, reauth, upgrade)             | `npm run test:e2e:local -- <four specs>`                        | 170 s (60 tests, cached build) |
| Full suite, cold build (255 tests: 235 pass, 20 skipped) | `npm run test:e2e:local`                                        | 214 s (build 54 s, test 152 s) |

Run the full suite for broad changes or anything touching auth, the proxy or shared layouts.

## Quarantined tests

A test that fails on a clean `main` is quarantined, never skipped silently: `test.fixme(...)` with the Jira key in a comment beside it. Remove the `.fixme` in the PR that closes the ticket. The full local run is green with exactly these left out:

| Test                                                        | Spec                                            | Ticket                                                    | Why                                                                              |
| ----------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `should successfully upgrade from free to pro tier` (fixme) | `subscription-simple.spec`                      | [KAN-157](https://storecart.atlassian.net/browse/KAN-157) | The Stripe webhook cannot reach a local server (needs `stripe listen`)           |
| `should display users table with correct columns` (fixme)   | `admin.spec`                                    | [KAN-196](https://storecart.atlassian.net/browse/KAN-196) | `locator('table')` is ambiguous (24 tables, 23 hidden) when there are many users |
| `should display 404 for non-existent user` (fixme)          | `admin.spec`                                    | [KAN-198](https://storecart.atlassian.net/browse/KAN-198) | Flaky: `waitForHydration` times out on the not-found page (3 of 5 repeats)       |
| 14 skipped: env-gated, stubs, data-gated                    | `subscription`, `pricing`, `billing-management` | [KAN-197](https://storecart.atlassian.net/browse/KAN-197) | See the ticket for the list                                                      |
| 2FA section and authenticator enrolment (skipped)           | `dashboard`, `settings-totp`                    | KAN-125                                                   | Sign-in 2FA is parked; the controls are hidden                                   |
| Data export section (skipped)                               | `dashboard`                                     | KAN-114                                                   | Switched off until KAN-114                                                       |

KAN-154, 155, 156 and 158 are Done (fixed, or not reproducible on current `main`) and are no longer baseline failures.

## Ports

Each checkout gets a stable port in 3100-3899 derived from its path; the script walks forward if it is busy. The build bakes the port in (`NEXT_PUBLIC_APP_URL`), so a different port forces a rebuild, which is why the default is stable. Set `E2E_PORT=3177` to choose one yourself (the script stops if it is taken).

## Troubleshooting

- **`.env.e2e.local is missing`**: copied from the main checkout when it exists there. Otherwise create it as described in [testing.md](testing.md) (storecart-test Firebase web config, `FIREBASE_ADMIN_*`, test `DATABASE_URL`, accounts from `npm run test:setup`). It is gitignored; never commit it.
- **`E2E_PORT=... is already in use`**: unset `E2E_PORT`, or stop the process (`npm run dev:kill` clears stuck dev servers).
- **Server did not start (cold or crashed)**: read `test-results/e2e-local-server.log`. `scripts/e2e-start.mjs` refuses a build made for another Firebase project or port; delete `.next-e2e` to force a rebuild.
- **Tests time out in `page.goto`**: too many workers for the machine; add `--workers=2`.
- **Stale build**: any change to tracked or untracked files triggers a rebuild automatically; delete `.next-e2e` to force one.
- **Shared `node_modules`**: it is a link to the main checkout's. Running `npm ci` in the main checkout changes it for every worktree. Set `E2E_LOCAL_NO_LINK=1` for your own copy. If the lockfile later differs from the main checkout's, the script removes only the link and runs `npm ci`.
- **Deleting a worktree**: it holds a link to the main checkout's `node_modules`. Remove the link first (`rmdir node_modules` in Windows `cmd`, `rm node_modules` elsewhere, no recursive flag), then remove the worktree. A recursive delete that follows the link would destroy the main checkout's dependencies.
- **Plain `npm run test:e2e`** still works and starts `next dev`. The setup project now allows 90 s and the post-login redirect 45 s, so a cold dev compile no longer fails the login, but the prebuilt run is much faster.

## Not covered

This does not enable E2E in CI (`E2E_ENABLED` stays `false`) and does not change what any test asserts. Specs that need `TEST_ADMIN_EMAIL`/`TEST_USER_EMAIL` skip until `npm run test:setup` has created the accounts. The optional nightly Playwright workflow is a separate story.
