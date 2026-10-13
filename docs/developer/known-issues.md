# Known issues

**Last updated:** 2026-10-12

Items are listed by area. Each one is either tracked by a Jira key or marked as untracked.

## Tooling

- **There is no `npm run test:integration` script.** KAN-148 removed it because there are no integration tests. Add the script back with the first real integration test.
- **`npm run build` needs `DATABASE_URL`.** KAN-140. It no longer needs `FIREBASE_ADMIN_*` (fixed in KAN-136).
- **ESLint works.** `npm run lint` runs `eslint .` with the flat config `eslint.config.mjs` (fixed in KAN-111).
- **`npm audit` still reports 21 findings (1 critical, 8 high, 11 moderate, 1 low), with no runtime high or critical.** KAN-138 fixed every runtime critical and high, and CI blocks on `npm audit --omit=dev --audit-level=high`. What remains:
  - `tar` 6.2.1 under `@capacitor/cli` 6 (1 critical, 1 high; several advisories). Dev-only and accepted: the CLI only unpacks Capacitor templates. KAN-148 checked the upgrade: `@capacitor/cli` 7 and 8 depend on `tar` 7, but the CLI major must match `@capacitor/core`, `android` and `ios` (6 here). With CLI 7 against platform 6, `cap add android` failed (`ENOENT ... capacitor.plugins.json`). Capacitor stays untouched in StoreCart (the mobile app is E21.2, KAN-109), so the finding stays until all Capacitor packages are upgraded together. A `tar` 7 override was also rejected earlier because `@capacitor/cli` 6 calls `require("tar").default.extract`, which tar 7 does not export.
  - `braces` (GHSA-vfj7-8cjw-p6xm, no patched release) reached through `tailwindcss` 3, `chokidar`, `micromatch`, `fast-glob` and `eslint-config-next`, at build and lint time only. Tracked in KAN-150 (Tailwind 4 migration).
  - 8 runtime moderates from `uuid` under `firebase-admin` 13 (needs a caller-supplied buffer, which these libraries do not use with untrusted input). Tracked in KAN-151 (`firebase-admin` 14).
- **`eslint-plugin-react-hooks` is pinned to exactly 7.0.1** (`overrides` in `nextjs-frontend/package.json`). 7.1.x adds rules that report 5 errors in the `dashboard/profile`, `dashboard/security`, `dashboard/settings` and `dashboard/settings/billing` pages. Fix those pages, then drop the override. KAN-152.
- **Pre-commit hooks exist** (`.pre-commit-config.yaml`, KAN-111). CI landed with KAN-27.

## Tests

- **Frontend coverage is about 5%** (lines 5.35%, statements 5.34%, functions 2.15%, branches 3.2% on Vitest 5; thresholds in `vitest.config.ts` are set to these) against the 80% target. The PO decision on the coverage rule is KAN-139.
- **E2E baseline is red.** The first Chromium run gave 67 passed, 32 failed and 137 skipped. Being fixed in KAN-113.
- **`npm run test:setup` runs the old script on `main`.** `scripts/create-test-user.mjs` is replaced by `setup-e2e-accounts.mjs` (lands with KAN-113).
- **Foundation check fails by design** until KAN-51 (lands with KAN-113).

## Backend

- **The backend has almost no features.** KAN-30 removed the template's auth, `Item` example and email. Only `GET /health` and `GET /health/ready` exist; auth (ADR-003), the platform and store models, error types, Sentry and rate limiting come in later stories.
- **asyncpg and SQLAlchemy are not exercised against a real database in CI.** The backend tests use fake sessions, so the upgrades to asyncpg 0.32 and SQLAlchemy 2.1 are checked only by import, type checks and the offline Alembic run. KAN-112 verifies behaviour against Neon.
- **The Alembic tree is one platform baseline.** Revision `0001` creates the platform tables (KAN-36); `alembic upgrade head` is run in CI only against a throwaway Postgres container, and never by a deploy (ADR-011). The Prisma-managed tables in Neon are not yet migrated to it; the data move belongs to the story that retires Prisma (KAN-51).
- **Store database migrations are not built yet.** Planned for E7.

## Docs drift

- **`.claude/CLAUDE.md` names differ from `.env.example`.** CLAUDE.md lists `FIREBASE_PROJECT_ID` and `STRIPE_PRICE_ID_PRO_MONTHLY`. The real names are `FIREBASE_ADMIN_PROJECT_ID` and `STRIPE_PRICE_ID_PRO`. Use `.env.example` as the reference. Untracked.
- **Parts of the root `README.md` are from the old boilerplate.** Its Quick Start describes the Prisma-based setup, and it linked a `GUIDE.md` that KAN-146 removed (its accurate parts are now in these pages). Do not follow the outdated parts; use [getting-started.md](getting-started.md). The README's pre-commit section is current. Untracked.

## Open questions

- **Does the FastAPI service key count as a Foundation-rule secret?** `BACKEND_INTERNAL_KEY` (planned, ADR-003) will be a server secret in the Next.js environment, and `npm run foundation:check` does not flag it. Decide before KAN-51 is closed. See [security.md](security.md#server-secrets-and-database-access). Untracked.

## Open bug tickets

Open bug tickets from the KAN-113 parity inventory (council triage, 2026-10-11). Jira is the source of truth for their status.

- KAN-123: the email-verified gate trusted a cookie the client can write. Fixed on the legacy Next.js boundary: the signed `email_verified` claim is enforced server-side (`src/lib/auth/verified-session.ts`) and the proxy no longer reads the cookie. FastAPI enforcement (ADR-003) still lands with the E3 port.
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
