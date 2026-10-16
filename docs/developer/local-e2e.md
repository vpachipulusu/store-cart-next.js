# Running Playwright E2E locally

**Last updated:** 2026-10-16 (KAN-157)

CI skips Playwright (`E2E_ENABLED=false`), so developers run E2E before opening a PR for user-facing changes. This page is the fast path. Test accounts, the test Firebase project and the test database are described in [testing.md](testing.md).

## The command

From `nextjs-frontend/`:

```bash
npm run test:e2e:local -- src/__tests__/e2e/touch-targets.spec.ts src/__tests__/e2e/theme-contrast.spec.ts
```

Everything after `--` goes to Playwright (spec paths, `--grep`, `--headed`, `--workers=2`). With no spec it runs every spec in the chromium project.

What it does, in order (a timing table is printed at the end):

| Step         | What happens                                                                                                                                                                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `setup`      | Copies missing `.env`, `.env.local`, `.env.e2e.local` from the main checkout. Links `node_modules` to the main checkout's when `package-lock.json` is identical, otherwise `npm ci --prefer-offline`. Installs Chromium only if it is not in the global Playwright cache. |
| `build`      | `next build --webpack` into `.next-e2e` (never your `.next`). Skipped when the commit, uncommitted edits, port and `.env.e2e.local` are unchanged since the last build.                                                                                                   |
| `serve+warm` | `next start` on a free port, then requests `/`, `/login`, `/signup`, `/pricing` and `/dashboard` once.                                                                                                                                                                    |
| `test`       | `playwright.local.config.ts`: chromium plus the auth setup project, up to 4 workers (CPU count / 2).                                                                                                                                                                      |
| cleanup      | The server process tree is stopped on exit and on Ctrl+C. Server output is in `test-results/e2e-local-server.log`.                                                                                                                                                        |

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

**1. `nextjs-frontend/.env.e2e.local`** (gitignored; the script copies it from the main checkout into a worktree). It holds the dedicated Firebase **test** project `storecart-test` (public web config plus the `FIREBASE_ADMIN_*` service account, added by the owner), Stripe **test-mode** keys and price ids (`STRIPE_PRICE_ID_PRO_YEARLY` is the discounted yearly test price), and the accounts written by `npm run test:setup` (`TEST_USER_*`, `TEST_ADMIN_*`). Details and the "never mix dev and test" checks are in [testing.md](testing.md#dedicated-firebase-test-project-and-test-database). Never paste values into chat, tickets or commits.

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

## Stripe webhooks (KAN-157)

Stripe cannot reach `localhost`, so a checkout completes at Stripe but the app never learns it ("Processing Your Subscription..." forever). The backend receives the events at `POST /webhooks/stripe` and verifies each one with `STRIPE_WEBHOOK_SECRET`. For e2e the Stripe CLI forwards test-mode events to your local uvicorn. The Stripe specs run only with `E2E_STRIPE=1` (`E2E_ENABLED` is unrelated and stays `false`).

**Locally**, after the backend from step 2 above is up, in a separate terminal from `nextjs-frontend/`:

```bash
export BACKEND_API_URL=http://127.0.0.1:8170          # your uvicorn
node scripts/e2e-stripe-listen.mjs                   # = stripe listen --forward-to $BACKEND_API_URL/webhooks/stripe
```

- The script reads `STRIPE_SECRET_KEY` from the environment or `.env.e2e.local`, refuses anything but a test-mode key, and gives it to the CLI through `STRIPE_API_KEY`, so it never appears on a command line. Without a key it uses the CLI login (`stripe login`; the CLI login expires, so run it again if `stripe listen` answers `api_key_expired`).
- **The backend must run with the secret `stripe listen` prints.** `.env.e2e.local` holds it as `STRIPE_WEBHOOK_SECRET` (the same variable the backend reads); it is stable for one Stripe account, so set it once. To check or refresh it: `node scripts/e2e-stripe-listen.mjs --print-secret` prints it (do not paste it anywhere). If the backend has a different secret, every event is answered `400` and the test times out.
- Start the backend with the `STRIPE_*` variables from `.env.e2e.local`, including the four `STRIPE_PRICE_ID_{PRO,ENTERPRISE}_{MONTHLY,YEARLY}` names. Keep the forwarder running while the tests run; its log shows each event and the backend's status.

Then run the spec with the flag in the test shell:

```bash
E2E_STRIPE=1 npm run test:e2e:local -- src/__tests__/e2e/subscription-simple.spec.ts
```

**In CI** (`.github/workflows/e2e.yml`, still switched off by `E2E_ENABLED`): when the repository variable `E2E_STRIPE` is `true`, the job installs a pinned Stripe CLI (checksum verified), runs `stripe listen --print-secret` and exports the result as `STRIPE_WEBHOOK_SECRET` (masked), forwards events to `BACKEND_API_URL` (variable `E2E_BACKEND_API_URL`, default `http://127.0.0.1:8000`) and sets `E2E_STRIPE=1` for the Playwright step. It uses the test-mode key `E2E_STRIPE_SECRET_KEY` from the `e2e-test` environment, which the job's check step already restricts to `sk_test_`/`rk_test_`. The job does not start a backend yet; when one is added it must start after the forwarding step so it picks up the exported secret. Alternative if forwarding from the runner is ever unsuitable: register a test-mode webhook endpoint on a public deployed test backend and give the backend that endpoint's signing secret.

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

| Test                                                                                                  | Spec                                 | Ticket                                                    | Why                                                                                                                                                                                                |
| ----------------------------------------------------------------------------------------------------- | ------------------------------------ | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stripe Checkout upgrade test (skipped unless `E2E_STRIPE=1`)                                          | `subscription-simple.spec`           | [KAN-157](https://storecart.atlassian.net/browse/KAN-157) | Needs Stripe Checkout and the webhook forwarded to the backend: see [Stripe webhooks](#stripe-webhooks-kan-157)                                                                                    |
| Stripe Checkout, test cards, auto-renewal toggle and saved-card tests (skipped unless `E2E_STRIPE=1`) | `subscription`, `billing-management` | [KAN-157](https://storecart.atlassian.net/browse/KAN-157) | Skipped by default. With `E2E_STRIPE=1` and the webhook forwarded they still need a real Stripe subscription or card, which an admin grant does not create (KAN-157 revived only the upgrade test) |
| 2FA section and authenticator enrolment (skipped)                                                     | `dashboard`, `settings-totp`         | KAN-125                                                   | Sign-in 2FA is parked; the controls are hidden                                                                                                                                                     |
| Data export section (skipped)                                                                         | `dashboard`                          | KAN-114                                                   | Switched off until KAN-114                                                                                                                                                                         |

KAN-154, 155, 156, 158, 196 and 198 are Done (fixed, or not reproducible on current `main`) and are no longer baseline failures.

## Seeding an organisation on Pro (KAN-197)

`loginAsThrowawayAccountOnPro` (`helpers/e2e-utils.ts`) gives a throwaway account an organisation on the Pro plan without Stripe: the saved admin session calls the admin grant API (`PUT /v1/admin/subscriptions/{id}/grant`). It needs the saved admin session (`auth.setup.ts`), an admin account with the `subscriptions.grant` permission (the `super_admin` insert above gives it) and `BACKEND_INTERNAL_KEY` in the test shell; without the key the tests fail rather than skip. A grant has no Stripe subscription, so use it for plan-display tests only (pricing "Current Plan"), not for auto-renewal or saved cards.

## Ports

Each checkout gets a stable port in 3100-3899 derived from its path; the script walks forward if it is busy. The build bakes the port in (`NEXT_PUBLIC_APP_URL`), so a different port forces a rebuild, which is why the default is stable. Set `E2E_PORT=3177` to choose one yourself (the script stops if it is taken).

## Troubleshooting

- **`.env.e2e.local is missing`**: copied from the main checkout when it exists there. Otherwise create it as described in [testing.md](testing.md) (storecart-test Firebase web config, `FIREBASE_ADMIN_*`, accounts from `npm run test:setup`). It is gitignored; never commit it.
- **`E2E_PORT=... is already in use`**: unset `E2E_PORT`, or stop the process (`npm run dev:kill` clears stuck dev servers).
- **Server did not start (cold or crashed)**: read `test-results/e2e-local-server.log`. `scripts/e2e-start.mjs` refuses a build made for another Firebase project or port; delete `.next-e2e` to force a rebuild.
- **Tests time out in `page.goto`**: too many workers for the machine; add `--workers=2`.
- **Stale build**: any change to tracked or untracked files triggers a rebuild automatically; delete `.next-e2e` to force one.
- **Shared `node_modules`**: it is a link to the main checkout's. Running `npm ci` in the main checkout changes it for every worktree. Set `E2E_LOCAL_NO_LINK=1` for your own copy. If the lockfile later differs from the main checkout's, the script removes only the link and runs `npm ci`.
- **Deleting a worktree**: it holds a link to the main checkout's `node_modules`. Remove the link first (`rmdir node_modules` in Windows `cmd`, `rm node_modules` elsewhere, no recursive flag), then remove the worktree. A recursive delete that follows the link would destroy the main checkout's dependencies.
- **Plain `npm run test:e2e`** still works and starts `next dev`. The setup project now allows 90 s and the post-login redirect 45 s, so a cold dev compile no longer fails the login, but the prebuilt run is much faster.

## Not covered

This does not enable E2E in CI (`E2E_ENABLED` stays `false`) and does not change what any test asserts. Specs that need `TEST_ADMIN_EMAIL`/`TEST_USER_EMAIL` skip until `npm run test:setup` has created the accounts. The optional nightly Playwright workflow is a separate story.
