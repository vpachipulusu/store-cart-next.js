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

| Step         | What happens                                                                                                                                                                                                                                                                               |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `setup`      | Copies missing `.env`, `.env.local`, `.env.e2e.local` from the main checkout. Links `node_modules` to the main checkout's when `package-lock.json` and `prisma/schema.prisma` are identical, otherwise `npm ci --prefer-offline`. Runs `prisma generate` only when the client is missing or older than the schema. Installs Chromium only if it is not in the global Playwright cache. |
| `build`      | `next build --webpack` into `.next-e2e` (never your `.next`). Skipped when the commit, uncommitted edits, port and `.env.e2e.local` are unchanged since the last build.                                                                                                                    |
| `serve+warm` | `next start` on a free port, then requests `/`, `/login`, `/signup`, `/pricing` and `/dashboard` once.                                                                                                                                                                                     |
| `test`       | `playwright.local.config.ts`: chromium plus the auth setup project, up to 4 workers (CPU count / 2).                                                                                                                                                                                       |
| cleanup      | The server process tree is stopped on exit and on Ctrl+C. Server output is in `test-results/e2e-local-server.log`.                                                                                                                                                                         |

Why a production build and not `next dev`: dev compiles each route on first request (40-58 s for `/` and `/login` cold), which broke the one-time login and caused hydration timeouts under parallel workers. A production build has no per-route compile, so warming only primes the server.

## Expected timings

See the KAN-178 pull request for the measured before/after table. The one-off costs are `npm ci` (about 4 minutes, skipped by the node_modules link) and the cold `next build`. A repeat run with no code change skips the build and pays only server start, warm-up and the tests.

## Ports

Each checkout gets a stable port in 3100-3899 derived from its path; the script walks forward if it is busy. The build bakes the port in (`NEXT_PUBLIC_APP_URL`), so a different port forces a rebuild, which is why the default is stable. Set `E2E_PORT=3177` to choose one yourself (the script stops if it is taken).

## Troubleshooting

- **`.env.e2e.local is missing`**: copied from the main checkout when it exists there. Otherwise create it as described in [testing.md](testing.md) (storecart-test Firebase web config, `FIREBASE_ADMIN_*`, test `DATABASE_URL`, accounts from `npm run test:setup`). It is gitignored; never commit it.
- **`E2E_PORT=... is already in use`**: unset `E2E_PORT`, or stop the process (`npm run dev:kill` clears stuck dev servers).
- **Server did not start (cold or crashed)**: read `test-results/e2e-local-server.log`. `scripts/e2e-start.mjs` refuses a build made for another Firebase project or port; delete `.next-e2e` to force a rebuild.
- **Tests time out in `page.goto`**: too many workers for the machine; add `--workers=2`.
- **Stale build**: any change to tracked or untracked files triggers a rebuild automatically; delete `.next-e2e` to force one.
- **Shared `node_modules`**: it is a link to the main checkout's. Running `npm ci` in the main checkout changes it for every worktree. Set `E2E_LOCAL_NO_LINK=1` for your own copy. If the lockfile later differs from the main checkout's, the script removes only the link and runs `npm ci`.
- **Plain `npm run test:e2e`** still works and starts `next dev`. The setup project now allows 90 s and the post-login redirect 45 s, so a cold dev compile no longer fails the login, but the prebuilt run is much faster.

## Not covered

This does not enable E2E in CI and does not change what any test asserts. Specs that need `TEST_ADMIN_EMAIL`/`TEST_USER_EMAIL` still skip until `npm run test:setup` has created the accounts (see KAN-165).
