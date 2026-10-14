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

This does not enable E2E in CI and does not change what any test asserts. Specs that need `TEST_ADMIN_EMAIL`/`TEST_USER_EMAIL` still skip until `npm run test:setup` has created the accounts (see KAN-165).
