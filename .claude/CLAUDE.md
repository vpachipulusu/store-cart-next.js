# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
npm run test:integration # Vitest integration tests (src/__tests__/integration)
npm run test:e2e         # Playwright E2E tests (requires dev server running)
npm run test:e2e:ui      # Playwright with interactive UI
npm run test:coverage    # Vitest with coverage (80% threshold)
npm run test:all         # All Vitest + Playwright

# Database
npm run db:generate      # Regenerate Prisma client after schema changes
npm run db:push          # Push schema to DB without migration (dev)
npm run db:migrate       # Create and apply migration (production-safe)
npm run db:studio        # Open Prisma Studio GUI
npm run db:seed          # Seed database

# Mobile (Capacitor)
npm run build:mobile     # Build Next.js and sync with Capacitor
npm run cap:sync         # Sync web assets to native projects
npm run ios:build        # Build and open in Xcode
npm run android:build    # Build and open in Android Studio
```

## Next.js 16 Proxy (Middleware Migration) — CRITICAL

Next.js 16 replaced `middleware.ts` with a proxy convention:

- **File**: `src/proxy.ts` (not `src/middleware.ts`)
- **Export**: `export async function proxy(request: NextRequest)` — must be named `proxy`

The build will fail with "Proxy is missing expected function export name" if the function is named `middleware`. The `config` export (matcher) and all functionality remain the same.

## Architecture Overview

### Authentication Flow

Firebase handles authentication on both client and server:

1. **Client**: Firebase client SDK (`src/lib/firebase/client.ts`) authenticates the user and returns an ID token.
2. **Server**: `verifyTokenAction` in `src/app/actions/auth-actions.ts` verifies the token via Firebase Admin SDK, syncs the user to PostgreSQL, records login history, and sets two cookies:
   - `session` (httpOnly) — Firebase session cookie, 5-day expiry
   - `email-verified` (readable by proxy) — enforced by `src/proxy.ts` to gate protected routes
3. **Proxy** (`src/proxy.ts`) — handles route protection, rate limiting, CORS, and security headers at the edge.

Admin role verification cannot be done in the proxy (Firebase token verification requires Node.js runtime). Admin access is verified server-side in each admin API route/page.

### Data Layer

- **Prisma client singleton**: `src/lib/db/client.ts` — import `db` from `@/lib/db/client`
- **Firebase Admin**: `src/lib/firebase/admin.ts` — import `adminAuth`
- **Stripe**: `src/lib/stripe/` — lazy-initialized singleton; webhook handler validates signatures via `STRIPE_WEBHOOK_SECRET`
- **Stripe prices** are fetched from the API and cached for 1 hour using `unstable_cache` in `src/config/subscriptions.ts`

### Server Actions Pattern

All server actions are in `src/app/actions/` and follow this pattern:
```typescript
'use server';
// Returns structured response
type ActionResponse<T = any> = { success: boolean; data?: T; error?: string };
// Validate with Zod, call db/services, revalidate cache with revalidatePath()
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

Three tiers: `free`, `pro`, `enterprise`. Defined in `src/config/subscriptions.ts`. Stripe price IDs come from env vars (`STRIPE_PRICE_ID_PRO_MONTHLY`, etc.). Subscription state is stored on the `User` model alongside `stripeCustomerId` and `stripeSubscriptionId`.

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
FIREBASE_PROJECT_ID                   # Firebase Admin SDK
FIREBASE_CLIENT_EMAIL
FIREBASE_PRIVATE_KEY
STRIPE_SECRET_KEY
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
STRIPE_WEBHOOK_SECRET
STRIPE_PRICE_ID_PRO_MONTHLY
STRIPE_PRICE_ID_PRO_YEARLY
STRIPE_PRICE_ID_ENTERPRISE_MONTHLY
STRIPE_PRICE_ID_ENTERPRISE_YEARLY
SENTRY_AUTH_TOKEN                     # Optional; disables source maps if absent
```

## Testing Notes

- **E2E auth setup**: `src/__tests__/e2e/auth.setup.ts` runs before browser tests. Use `npm run test:setup` to create the test user.
- **playwright.config.ts** has a stale `pnpm dev` reference in `webServer.command` — the project uses `npm run dev`. Start the dev server manually before running E2E tests locally.
- Vitest coverage thresholds are 80% for branches, functions, lines, and statements.
- MSW (`msw`) is available for mocking HTTP in Vitest tests.

## Package Manager

This project uses **npm** exclusively. Do not use `pnpm` or `yarn`.
