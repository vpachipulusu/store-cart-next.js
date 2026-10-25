# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

StoreCart is a monorepo:

- `nextjs-frontend/` — the Next.js app. **Run every npm command below from this folder.**
- `fastapi_backend/` — FastAPI service (uv), adapted from vintasoftware/nextjs-fastapi-template.

Plan and decisions: `.claude/plans/storecart-plan.md`. Backlog: `.claude/plans/backlog/` (Jira key map in `jira-map.md`).

## Work tracking (Jira) — REQUIRED

All work is tracked in Jira project **Store Cart** (key `KAN`, https://storecart.atlassian.net/browse/KAN). Workflow (exact Jira status names): **To-do → In Progress → In Review → Done**.

1. **Pick up** only a story in **To-do** (JQL: `project = KAN AND issuetype = Story AND status = "To-do" ORDER BY key`). Work epics in order (E1 → E2 → …), and within Foundation follow the **start order** in `.claude/plans/storecart-plan.md` (not key order), unless the user says otherwise. Respect "Depends on" / "Blocks" notes in story descriptions. Never take a story that is already In Progress or In Review.
2. **Before writing any code**, transition the story to **In Progress** and add a comment saying it was picked up and on which branch.
3. **Branch** `<type>/KAN-<n>-<short-slug>`; **commits** `<type>(KAN-<n>): <description>` (conventional commit types).
4. The story's **acceptance criteria are the definition of done**. Do not widen scope; propose a new story to the user for extra work.
5. **Opening a PR**: link the PR in a comment and transition the story to **In Review**.
6. **Merged and acceptance criteria verified**: transition to **Done**.
7. **Blocked**: keep the story In Progress and comment with the blocker and what is needed; do not abandon it silently.

## Commands

```bash
# Development
npm run dev              # Start dev server (uses webpack; runs dev-clean.cjs predev hook)
npm run dev:kill         # Kill stuck dev processes and remove lock files
npm run build            # Production build
npm run lint             # ESLint
npm run typecheck        # TypeScript type check without emitting

# Testing
npm run test:unit        # Vitest unit tests only (src/__tests__/unit)
npm run test:e2e:local -- <spec>  # Playwright against a production build (see Testing Notes); needs a backend
npm run test:e2e         # Raw Playwright (needs a server you started yourself)
npm run test:e2e:ui      # Playwright with interactive UI
npm run test:coverage    # Vitest with coverage (80% threshold)
npm run test:all         # All Vitest + Playwright

# Generated API client (backend branches regenerate; frontend branches never do)
npm run generate:client  # openapi.json -> src/lib/api/generated
npm run check:client     # fails when the committed client is stale

# Legacy Prisma (still used by files that move off it in KAN-48/49/50/51; add no new uses)
npm run db:generate      # Regenerate Prisma client after schema changes
npm run db:push          # Push schema to DB without migration (dev)
npm run db:seed          # Seed database

# Mobile (Capacitor)
npm run build:mobile     # Build Next.js and sync with Capacitor
npm run cap:sync         # Sync web assets to native projects
npm run ios:build        # Build and open in Xcode
npm run android:build    # Build and open in Android Studio
```

### Backend (run from `fastapi_backend/`, uv)

```bash
uv run ruff check . && uv run ruff format --check .     # lint + format (CI runs both)
uv run mypy                                              # blocking in CI
uv run pytest --cov                                      # coverage ratchet in pyproject.toml
uv run alembic upgrade head && uv run alembic check      # models must match migrations; one head per tree (`uv run alembic heads`, store tree: `-c alembic_store.ini`)
uv run python -m commands.generate_openapi_schema        # writes ../nextjs-frontend/openapi.json; then npm run generate:client
```

Real-route tests need a throwaway local Postgres (`TEST_DATABASE_URL` pointing at a `*_test` database; see the docs in `docs/developer/backend-*.md`). Backend details: `fastapi_backend/CLAUDE.md`.

## Next.js 16 Proxy (Middleware Migration) — CRITICAL

Next.js 16 replaced `middleware.ts` with a proxy convention:

- **File**: `src/proxy.ts` (not `src/middleware.ts`)
- **Export**: `export async function proxy(request: NextRequest)` — must be named `proxy`

The build will fail with "Proxy is missing expected function export name" if the function is named `middleware`. The `config` export (matcher) and all functionality remain the same.

## Architecture Overview

### Two apps, one direction

The browser never calls FastAPI. Next.js server code (server components, server actions, route handlers) is the only caller (plan decision D14). Server-only wrappers in `src/lib/api/` call the generated SDK through `callBackend`, which sends `X-Internal-Key` (`BACKEND_INTERNAL_KEY`) and the current `session` cookie. ESLint forbids importing `@/lib/api/generated*` outside `src/lib/api/**` and tests.

### Authentication Flow

1. **Client**: Firebase client SDK (`src/lib/firebase/client.ts`) authenticates the user and returns an ID token.
2. **Server**: `verifyTokenAction` in `src/app/actions/auth-actions.ts` sends the token to the backend, which verifies it (Firebase Admin), syncs the user, records login history and returns the session; the action sets the httpOnly `session` cookie (Firebase session cookie, 5-day expiry). The backend owns users, sessions, login history and 2FA (`POST /v1/auth/session/refresh`, re-authentication for 2FA disable and account deletion).
   - The client-writable `email-verified` cookie is no longer issued or trusted (KAN-123). Verified email is enforced server-side from the signed `email_verified` claim in the session cookie, with revocation checking, by `src/lib/auth/verified-session.ts` (layouts, server actions, admin helpers).
3. **Proxy** (`src/proxy.ts`) — handles session-presence route protection, rate limiting, CORS, and security headers at the edge.

Admin role verification cannot be done in the proxy (Firebase token verification requires Node.js runtime). Admin access is verified server-side in each admin API route/page. One ticket at a time may edit `auth-actions.ts`.

### Data Layer

- **Platform data** (users, organisations, stores, billing) lives in the FastAPI platform database (SQLAlchemy async + Alembic; platform tree `alembic_migrations/`, store tree `alembic_store/`, each with a single head).
- **Store data**: each store has its own database. Connection strings are encrypted at rest (`app/services/store_secrets.py`), opened only through `get_store_session` (`app/services/store_sessions.py`), and created by a `DatabaseProvisioner` (`app/services/store_provisioning.py`; `STORE_DB_PROVIDER` is `local` for development only, `neon` otherwise). A ruff TID251 rule bans creating engines anywhere else.
- **Prisma** (`src/lib/db/client.ts`) is legacy: files still import it until KAN-48/49/50/51 move them to the API. Add no new uses.
- **Firebase Admin**: `src/lib/firebase/admin.ts` — import `adminAuth` (session verification only)
- **Stripe** is handled by the backend (webhook and Billing per organisation). The frontend calls the org billing API through `src/lib/api/billing.ts` and `src/app/actions/subscription-actions.ts`.
- **Selected store**: the dashboard store selection is a cookie *preference*, validated on every request against the user's own stores by `getCurrentStoreSelection()`. It is not an authorization boundary: anything scoped by store must call it on the server and the backend must authorize the store id itself.

### Server Actions Pattern

All server actions are in `src/app/actions/` and follow this pattern:

```typescript
"use server";
// Returns structured response
type ActionResponse<T = any> = { success: boolean; data?: T; error?: string };
// Validate with Zod, call the src/lib/api wrappers, revalidate cache with revalidatePath()
```

### Route Structure

```
src/app/
├── (auth)/          # login, signup, reset-password, verify-email
├── (admin)/admin/   # analytics, audit-logs, seo, settings, subscriptions, users
├── dashboard/       # customer dashboard (protected)
├── actions/         # all server actions
├── api/
│   ├── auth/        # login, logout, signup, clear-session, stripe
│   └── webhooks/    # Stripe webhook handler (public, no auth)
└── pricing/         # smart pricing page (adapts to auth state)
```

### Subscriptions

Three tiers: `free`, `pro`, `enterprise`. Plans and limits are defined in `src/config/subscriptions.ts` and the backend plans config. Stripe price IDs come from env vars (`STRIPE_PRICE_ID_PRO_MONTHLY`, etc.). Subscription state belongs to the **organisation** (billing is per organisation, read and changed through the backend org billing API), not to the user.

### Logging

Winston logger at `src/lib/logger.ts`. Daily rotating log files in `logs/`. The webpack config excludes `logs/` from file watching to prevent HMR churn.

### Path Alias

`@/` resolves to `src/`. Used throughout the codebase.

## Key Environment Variables

```env
DATABASE_URL                          # PostgreSQL connection string
NEXT_PUBLIC_FIREBASE_API_KEY          # Firebase client config
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
NEXT_PUBLIC_FIREBASE_PROJECT_ID
FIREBASE_ADMIN_PROJECT_ID             # Firebase Admin SDK (src/lib/firebase/admin.ts)
FIREBASE_ADMIN_CLIENT_EMAIL
FIREBASE_ADMIN_PRIVATE_KEY
STRIPE_SECRET_KEY
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
STRIPE_WEBHOOK_SECRET
STRIPE_PRICE_ID_PRO_MONTHLY
STRIPE_PRICE_ID_PRO_YEARLY
STRIPE_PRICE_ID_ENTERPRISE_MONTHLY
STRIPE_PRICE_ID_ENTERPRISE_YEARLY     # Preferred names; legacy STRIPE_PRICE_ID_{FREE,PRO,ENTERPRISE} are optional tier-mapping fallbacks only
BACKEND_API_URL                       # FastAPI base URL (server-only)
BACKEND_INTERNAL_KEY                  # Sent as X-Internal-Key (server-only)
SENTRY_AUTH_TOKEN                     # Optional; disables source maps if absent
```

Backend-only variables (set on the FastAPI service, see `fastapi_backend/app/core/config.py` and `docs/developer/`):

```env
STORE_DB_ENCRYPTION_KEY               # base64url 32 bytes; required outside local/test/Vercel preview (store connection strings)
STORE_DB_ENCRYPTION_KEY_PREVIOUS      # optional comma-separated retired keys, decrypt-only during rotation
STORE_DB_PROVIDER                     # local (development only) or neon
NEON_API_KEY, NEON_PROJECT_ID, NEON_BRANCH_ID, NEON_ROLE_NAME   # required when STORE_DB_PROVIDER=neon
TOTP_ENCRYPTION_KEY                   # optional Fernet key for 2FA secrets
BILLING_RETURN_URL_ORIGINS            # allowed origins for Stripe return URLs
RESEND_API_KEY, EMAIL_FROM            # Resend email (set together); unset disables email (KAN-62)
APP_PUBLIC_URL                        # https origin of the Next.js app for links in emails; required outside local/test to create invitations
```

## Testing Notes

- **E2E auth setup**: `src/__tests__/e2e/auth.setup.ts` runs before browser tests. Use `npm run test:setup` to create the test user.
- **Local E2E**: `npm run test:e2e:local -- <spec>` builds a production bundle and starts it on a per-checkout port (about 2 minutes cold, 30 seconds cached). Never use `next dev` for E2E (first-request compile times break auth setup). It needs a running backend: start your own throwaway Postgres 17 container and uvicorn on free ports (not other sessions' ports), then export `BACKEND_API_URL` and the same `BACKEND_INTERNAL_KEY` before running (`docs/developer/local-e2e.md`). Remove the node_modules link before deleting a worktree.
- **Vercel previews are opt-in** (KAN-212): only `main` deploys. A branch or PR builds nothing unless the latest commit message contains `[deploy preview]` (`scripts/vercel-ignore-build.sh`; see `docs/developer/`). Do not expect a preview URL by default, and do not add the marker unless a preview is really needed (Hobby plan: 100 deployments per day).
- **CI**: only the `CI gate` check matters (Vercel checks are ignored). `E2E_ENABLED` stays `false` in CI, so every story's E2E specs are written and run locally, with the command and result in the PR description.
- After a clean install (`npm ci`), run `npm run db:generate` before `npm run typecheck` — the Prisma client is not generated automatically (until KAN-51 removes Prisma).
- Vitest coverage thresholds are 80% for branches, functions, lines, and statements. The backend has a coverage ratchet in `fastapi_backend/pyproject.toml`.

## Review before merge

Run the ECC reviewers on every PR diff before merging: `security-reviewer` for auth, payments, secrets, SQL and external calls; the language reviewer (`typescript-reviewer`, `python-reviewer`, `react-reviewer`, `fastapi-reviewer`); `database-reviewer` for migrations and queries. Fix CRITICAL and HIGH findings first. Coordinator-owned files that developer branches must not edit: `.env.example`, `.claude/CLAUDE.md`, `known-issues.md`.

## ECC (agents, skills, hooks)

The repo enables the ECC plugin in `.claude/settings.json` (`ecc@ecc`), so every clone and worktree gets ECC's subagents, skills and hooks. Call agents by their plugin names (`ecc:<name>`). Do not add ECC hooks to this repo's settings: the plugin already registers them, and a second copy runs them twice. The project keeps only `.claude/hooks/guard.mjs`.

Required agent per kind of change (coordinator on every PR diff; developers on their own branch before opening the PR):

| Change | Agents |
|---|---|
| Any code change | `ecc:code-reviewer` plus the language reviewer: `ecc:typescript-reviewer` / `ecc:react-reviewer` (frontend), `ecc:python-reviewer` / `ecc:fastapi-reviewer` (backend) |
| Auth, payments, secrets, user input, external calls, crypto | `ecc:security-reviewer` |
| Migrations, SQL, models | `ecc:database-reviewer` |
| New feature or bug fix | `ecc:tdd-guide` (tests first) |
| Allocation, design decisions | `ecc:architect` and `ecc:planner` (there is no separate product-manager agent; the rules below are its brief) |
| Failing build | `ecc:build-error-resolver` |

`general-purpose` is for plain searching only, never for review. The Jira merge comment lists which agents ran and what they found (CRITICAL and HIGH fixed first), so the review is verifiable.

### Allocation rules (give these to `ecc:architect` and `ecc:planner`)

- Pick bugs before features. Work only stories in To-do; a story's acceptance criteria are its definition of done and scope is never widened (propose a new story instead).
- Parked, do not touch: KAN-125, KAN-145 UI redesign stories stay on hold until the foundation work is done.
- At most 3 or 4 developers in parallel, on disjoint files. One ticket at a time on `auth-actions.ts`.
- One backend developer at a time by default (one Alembic head). A second backend developer may run alongside the first only if the story adds no Alembic revision, no platform model change and no `app/models/platform/__init__.py` edit, and does not edit `fastapi_backend/tests/conftest.py`, `tests/fakes.py`, `app/core/config.py` or `app/core/permissions.py`. Whichever PR merges second must, before the merges it: rebase on main, regenerate `openapi.json` and the client (`generate_openapi_schema`, then `npm run generate:client`; never hand-merge the generated files), and get a green `CI gate` on the rebased head SHA. That PR's description states the base SHA. The coordinator checks that the PR head contains main's current SHA before merging (a stale green run can merge two migrations into a double head).
- The OpenAPI client is regenerated only in backend branches.
- Coordinator-owned files that developer branches must not edit: `.env.example`, `.claude/CLAUDE.md`, `known-issues.md`.
- Only the `CI gate` check matters; Vercel checks are ignored. E2E specs are written and run locally with the command and result in the PR; `E2E_ENABLED` is never flipped.

### After a merge: pick the next task

When a developer PR is merged and its Jira story is Done, the coordinator immediately picks the next task (bugs before features, allocated with `ecc:architect` and `ecc:planner` per the rules above) and starts its developer session. It does not wait for the owner's signal or ask them to click start. 

## Package Manager

This project uses **npm** exclusively. Do not use `pnpm` or `yarn`.


### Review findings: fix small ones in the PR, no follow-up stories

- Small findings (LOW, cosmetic, or a cheap missing test: date locale, contrast, a duplicated string, a one-line guard) are fixed by the developer in the same PR before the coordinator merges. The coordinator sends them back to the developer session. It does not create a Jira story for them.
- Create a follow-up story only for sized work: a backend change, a new capability, a migration, or a finding that needs a design decision. Ask the owner before creating it.
- Small findings that are not fixed are listed in the Jira merge comment (agents ran, findings, fixed or not). They are not a backlog item.


### Speak to Architect if any developer is available

Speak to `ecc:architect` and `ecc:planner` if any developers are free. The work should be distributed between the developers without any conflict.


### Env files for local e2e

To run local e2e (`npm run test:e2e:local`), copy the owner's env files into your worktree's `nextjs-frontend/` folder from the main checkout: `C:\MainData\AI-Projects\store-cart-next.js\nextjs-frontend` (`.env.e2e.local`, `.env.local`, and `.env` only if `docs/developer/local-e2e.md` needs it).

- Copy with `cp` or `Copy-Item` only. Never open, read, cat, echo, grep or log these files, and never print any value in them. Refer to variables by name only.
- They are gitignored. Check `git status` shows them untracked-ignored, never stage them, and delete the copies when the run is done (before removing the worktree).
- Set `BACKEND_API_URL` and `BACKEND_INTERNAL_KEY` for your own throwaway backend by name, without printing the key.
- `E2E_ENABLED` stays `false` in CI and is never flipped.
- This covers copying only. Developers still do not read secrets, and the PR description gives the spec command and its pass/fail result, with no values.