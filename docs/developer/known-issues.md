# Known issues

**Last updated:** 2026-10-12

Items are listed by area. Each one is either tracked by a Jira key or marked as untracked.

## Tooling

- **ESLint cannot run.** `nextjs-frontend/.eslintrc.json` is the legacy format, but `eslint` is `^9`. Fixed in KAN-111 (lands with KAN-111).
- **`npm run lint` will not work on Next 16.** It calls `next lint`, which Next 16 removed. Use the ESLint fix in KAN-111 when it lands.
- **`npm run db:seed` points at a missing file.** It runs `tsx prisma/seed.ts`, and `nextjs-frontend/prisma/` has only `schema.prisma`. Untracked.
- **`npm run build` needs `FIREBASE_ADMIN_*`.** `firebase-admin` initialises at import, so the build fails without those variables. KAN-136.
- **`npm audit` reports 71 vulnerabilities, 10 critical.** KAN-138.
- **`engines` mismatch.** The team standard is Node 22, but `nextjs-frontend/package.json` declares `node >=20`. Untracked.
- **No CI or pre-commit hooks in the repo yet.** CI lands with KAN-27, pre-commit with KAN-111. Untracked in this file.

## Tests

- **Frontend coverage is about 2%** (lines; about 3% functions, 10% branches) against the 80% threshold, so `npm run test:coverage` fails. The PO decision on the coverage rule is KAN-139.
- **E2E baseline is red.** The first Chromium run gave 67 passed, 32 failed and 137 skipped. Being fixed in KAN-113.
- **`npm run test:setup` runs the old script on `main`.** `scripts/create-test-user.mjs` is replaced by `setup-e2e-accounts.mjs` (lands with KAN-113).
- **`dotenv` is imported but not declared.** `playwright.config.ts` and `setup-e2e-accounts.mjs` import `dotenv` (lands with KAN-113). It is not a direct dependency in `package.json`, so it works only through a transitive install. Untracked.
- **Foundation check fails by design** until KAN-51 (lands with KAN-113).

## Backend

- **mypy reports existing errors** (80 at the last verification), and a bare `uv run mypy` fails because `mypy.ini` has `files = src/**/*.py`. Config fix in KAN-111; errors from template code go with KAN-30.
- **No `/health` route.** The foundation check requires `GET /health`. Untracked.
- **Template configuration remains.** `app/config.py` still requires fastapi-users secrets (`ACCESS_SECRET_KEY`, `RESET_PASSWORD_SECRET_KEY`, `VERIFICATION_SECRET_KEY`), and the `Item` example model and routes are still present. Removed in KAN-30.
- **Store database migrations are not built yet.** Planned for E7.

## Docs drift

- **`.claude/CLAUDE.md` names differ from `.env.example`.** CLAUDE.md lists `FIREBASE_PROJECT_ID` and `STRIPE_PRICE_ID_PRO_MONTHLY`. The real names are `FIREBASE_ADMIN_PROJECT_ID` and `STRIPE_PRICE_ID_PRO`. Use `.env.example` as the reference. Untracked.
- **The root `README.md` is the old boilerplate README.** It describes Prisma-based setup and links `GUIDE.md`, which is in `nextjs-frontend/`. Do not follow it. Untracked.

## Open bug tickets

Open bug tickets from the KAN-113 parity inventory (council triage, 2026-10-11). Jira is the source of truth for their status.

- KAN-123: the email-verified gate trusts a cookie the client can write (confirmed; fixed in the E3 port).
- KAN-124: admins can grant themselves the `*` permission (confirmed; fixed in the E5 port).
- KAN-125: 2FA is never checked at login (confirmed).
- KAN-126: profile actions return the user row, including `twoFactorSecret` (partial: `updateUserProfileAction` leaks the full row).
- KAN-127: open redirects in the checkout and billing-portal return URLs (confirmed).
- KAN-128: the Stripe webhook acknowledges failed events and is not idempotent (confirmed).
- KAN-129: raw error messages, open CORS and no real rate limiting in auth paths (partial: raw errors and missing rate limiting confirmed; open CORS not reproducible).
- KAN-130: unauthenticated `/api/test-logging` route (confirmed; delete).
- KAN-131: move the e2e test accounts to a separate Firebase project and delete them before launch.
- KAN-136: `firebase-admin` initialises at import, so `npm run build` needs `FIREBASE_ADMIN_*`.
- KAN-137: the `src/proxy.ts` API gate only checks that some Bearer header or `session` cookie is present (any value passes), so every `/api/*` handler must verify the session itself; also a logout CSRF via `GET /api/auth/clear-session` and a spoofable `x-forwarded-for` IP stored in login history (needs triage; fix in the E3 port).
- KAN-138: `npm audit` reports 71 vulnerabilities, 10 critical.
- KAN-139: PO decision on the 80% coverage rule (frontend coverage is about 2%).
