# Known issues

**Last updated:** 2026-10-12

Items are listed by area. Each one is either tracked by a Jira key or marked as untracked.

## Tooling

- **`npm run test:integration` has no tests or folder.** KAN-146 removed the only placeholder, so the script finds nothing. Add the first real integration test, or drop the script. Untracked.
- **`npm run db:seed` points at a missing file.** It runs `tsx prisma/seed.ts`, and `nextjs-frontend/prisma/` has only `schema.prisma`. Untracked.
- **`npm run build` needs `DATABASE_URL`.** KAN-140. It no longer needs `FIREBASE_ADMIN_*` (fixed in KAN-136).
- **ESLint works.** `npm run lint` runs `eslint .` with the flat config `eslint.config.mjs` (fixed in KAN-111).
- **`npm audit` still reports 21 findings (1 critical, 8 high, 11 moderate, 1 low), with no runtime high or critical.** KAN-138 fixed every runtime critical and high, and CI blocks on `npm audit --omit=dev --audit-level=high`. What remains:
  - `tar` 6.2.1 under `@capacitor/cli` 6 (1 critical, 1 high; several advisories). Dev-only and accepted: the CLI only unpacks Capacitor templates. A `tar` 7 override was tried and rejected because `@capacitor/cli` 6 calls `require("tar").default.extract`, which tar 7 does not export, so `cap add` and `cap sync` would break. Capacitor is scheduled for removal in KAN-148, which clears these.
  - `braces` (GHSA-vfj7-8cjw-p6xm, no patched release) reached through `tailwindcss` 3, `chokidar`, `micromatch`, `fast-glob` and `eslint-config-next`, at build and lint time only. Tracked in KAN-150 (Tailwind 4 migration).
  - 8 runtime moderates from `uuid` under `firebase-admin` 13 (needs a caller-supplied buffer, which these libraries do not use with untrusted input). Tracked in KAN-151 (`firebase-admin` 14).
- **`eslint-plugin-react-hooks` is pinned to exactly 7.0.1** (`overrides` in `nextjs-frontend/package.json`). 7.1.x adds rules that report 5 errors in the `dashboard/profile`, `dashboard/security`, `dashboard/settings` and `dashboard/settings/billing` pages. Fix those pages, then drop the override. KAN-152.
- **Pre-commit hooks exist** (`.pre-commit-config.yaml`, KAN-111). CI landed with KAN-27.

## Tests

- **Frontend coverage is about 5%** (lines 5.35%, statements 5.34%, functions 2.15%, branches 3.2% on Vitest 5; thresholds in `vitest.config.ts` are set to these) against the 80% target. The PO decision on the coverage rule is KAN-139.
- **E2E baseline is red.** The first Chromium run gave 67 passed, 32 failed and 137 skipped. Being fixed in KAN-113.
- **`npm run test:setup` runs the old script on `main`.** `scripts/create-test-user.mjs` is replaced by `setup-e2e-accounts.mjs` (lands with KAN-113).
- **`dotenv` is imported but not declared.** `playwright.config.ts` and `setup-e2e-accounts.mjs` import `dotenv` (lands with KAN-113). It is not a direct dependency in `package.json`, so it works only through a transitive install. Lands with KAN-113 (dotenv devDependency).
- **Foundation check fails by design** until KAN-51 (lands with KAN-113).

## Backend

- **mypy reports existing errors.** A bare `uv run mypy` (it checks `app` and `commands`) found 31 errors on 2026-10-12. Errors from template code go with KAN-30.
- **No `/health` route.** The foundation check requires `GET /health`. Untracked.
- **Template configuration remains.** `app/config.py` still requires fastapi-users secrets (`ACCESS_SECRET_KEY`, `RESET_PASSWORD_SECRET_KEY`, `VERIFICATION_SECRET_KEY`), and the `Item` example model and routes are still present. Removed in KAN-30.
- **Store database migrations are not built yet.** Planned for E7.

## Docs drift

- **`.claude/CLAUDE.md` names differ from `.env.example`.** CLAUDE.md lists `FIREBASE_PROJECT_ID` and `STRIPE_PRICE_ID_PRO_MONTHLY`. The real names are `FIREBASE_ADMIN_PROJECT_ID` and `STRIPE_PRICE_ID_PRO`. Use `.env.example` as the reference. Untracked.
- **Parts of the root `README.md` are from the old boilerplate.** Its Quick Start describes the Prisma-based setup, and it linked a `GUIDE.md` that KAN-146 removed (its accurate parts are now in these pages). Do not follow the outdated parts; use [getting-started.md](getting-started.md). The README's pre-commit section is current. Untracked.

## Open questions

- **Does the FastAPI service key count as a Foundation-rule secret?** `BACKEND_INTERNAL_KEY` (planned, ADR-003) will be a server secret in the Next.js environment, and `npm run foundation:check` does not flag it. Decide before KAN-51 is closed. See [security.md](security.md#server-secrets-and-database-access). Untracked.

## Open bug tickets

Open bug tickets from the KAN-113 parity inventory (council triage, 2026-10-11). Jira is the source of truth for their status.

- KAN-123: the email-verified gate trusts a cookie the client can write (confirmed; fixed in the E3 port).
- KAN-124: admins can grant themselves the `*` permission (confirmed; fixed in the E5 port).
- KAN-125: 2FA is never checked at login (confirmed).
- KAN-126: profile actions return the user row, including `twoFactorSecret` (partial: `updateUserProfileAction` leaks the full row).
- KAN-127: open redirects in the checkout and billing-portal return URLs (confirmed).
- KAN-128: the Stripe webhook acknowledges failed events and is not idempotent (confirmed).
- KAN-129: raw error messages, open CORS and no real rate limiting in auth paths (partial: raw errors and missing rate limiting confirmed; open CORS not reproducible).
- KAN-130: unauthenticated `/api/test-logging` route (confirmed; deleted in KAN-146).
- KAN-131: move the e2e test accounts to a separate Firebase project and delete them before launch.
- KAN-136: `firebase-admin` initialised at import, so `npm run build` needed `FIREBASE_ADMIN_*` (fixed; it now initialises on first use).
- KAN-137: the `src/proxy.ts` API gate only checks that some Bearer header or `session` cookie is present (any value passes), so every `/api/*` handler must verify the session itself; also a logout CSRF via `GET /api/auth/clear-session` and a spoofable `x-forwarded-for` IP stored in login history (needs triage; fix in the E3 port).
- KAN-138: `npm audit` reported 71 vulnerabilities, 10 critical (fixed for criticals and runtime highs; see Tooling).
- KAN-139: PO decision on the 80% coverage rule (frontend coverage is about 2%).
- KAN-140: `npm run build` still needs `DATABASE_URL`.
