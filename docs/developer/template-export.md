# Template export (KAN-145)

**Status:** classification for product-owner review. Nothing is pushed to
`vpachipulusu/boiler-plate-fastapi-nextjs` until the owner has approved this list.
**Based on:** `main` at `9846fd1` (2026-10-24).

The template is the *platform* half of StoreCart: Firebase sign-in with the session cookie, users,
organisations, 2FA, profile, notifications, admin panel, audit log, settings, theme and font, logging,
Sentry, rate limiting, security headers, Stripe Billing (optional), FastAPI with Alembic, the path-filtered
CI gate, pre-commit, the local e2e runner, Vercel services and the developer docs and ADR templates.
Everything about stores, storefronts, products, carts, checkout, orders, refunds, Stripe Connect, Neon,
QStash and R2 is StoreCart's product and stays out.

## Classes

| Class | Meaning |
| --- | --- |
| **core** | Exported as is (brand strings and Jira keys scrubbed). |
| **core, trimmed** | Exported, then the StoreCart-only parts are cut out by hand (listed per file). |
| **module: billing** | Exported; documented in `docs/developer/modules.md` as the *Stripe Billing* module with a removal recipe. |
| **module: mobile** | Exported; the *Mobile (Capacitor)* module (owner decision 2026-10-13). |
| **StoreCart-only** | Not exported. |
| **rewrite** | Exported as a new generic file, not a copy. |

## What changed since the story was written (2026-10-12)

1. **Prisma is gone.** `nextjs-frontend/prisma/`, `src/lib/db/` and the `@prisma/*` packages no longer exist
   (KAN-48 to KAN-51). The admin panel reads FastAPI through `src/lib/api/admin-*.ts`. The criterion
   "Prisma models and admin panel" is met by the FastAPI platform models plus the Next.js admin pages.
2. **There is no email code.** ADR-0009 chose Resend, but neither app sends mail (the only `resend` hits are
   Stripe refund resends and Firebase's own verification mail). The template can ship "FastAPI base with
   Alembic"; the "and email" part does not exist to export. See open decision 3.
3. **The platform schema is entangled with stores.** `Organization` carries Stripe Connect columns,
   `Store` is a platform table, `admin_users.permissions` has `stores.*`, and platform migrations 0005 to
   0011 add store, Connect and notification-scope columns. The template gets **one fresh Alembic baseline
   generated from the trimmed models**, not the 11 StoreCart revisions (the history is fresh anyway).
4. **KAN-113 (fast e2e) is merged**, so the dependency is satisfied: `scripts/e2e-*.mjs`,
   `playwright.local.config.ts` and `docs/developer/local-e2e.md` are exported.

## Root

| Path | Class | Notes |
| --- | --- | --- |
| `.claude/CLAUDE.md` | rewrite | Generic agent guide: layout, commands, proxy note, server-action pattern. No Jira, no allocation rules. |
| `.claude/settings.json` | core, trimmed | Keep the permission allow/deny list and the guard hook. Drop the ECC plugin entries (owner's tooling, not the stack). |
| `.claude/hooks/guard.mjs` | core | Keep the force-push and merge guards; drop the `E2E_ENABLED` rule (StoreCart CI policy). |
| `.claude/plans/**` | StoreCart-only | Plan of record, backlog, Jira map. |
| `.claude/PRPs/**`, `.claude/progress/**` | StoreCart-only | Per-ticket notes and the Codex baton. |
| `.claude/skills/**` | StoreCart-only | Vendored copies of third-party skills. |
| `.env.example` | core | Already placeholders; rename `storecart` compose defaults to `app`. |
| `.gitattributes` | core | |
| `.gitignore` | core | Drop the `nextjs-frontend/prisma/migrations/` line (nothing left to ignore). |
| `.pre-commit-config.yaml` | core | Comment header scrubbed. |
| `.github/CODEOWNERS` | rewrite | `* @your-github-handle` placeholder. |
| `.github/ISSUE_TEMPLATE/bug_report.md`, `config.yml` | core | |
| `.github/ISSUE_TEMPLATE/story.md` | rewrite | Drop the Jira fields. |
| `.github/PULL_REQUEST_TEMPLATE.md` | core, trimmed | Drop the Jira key line and the Vercel-preview marker note. |
| `.github/dependabot.yml` | core | Add `npm` (`/nextjs-frontend`) and `pip`/`uv` (`/fastapi_backend`) ecosystems (AC: Dependabot). |
| `.github/scripts/ci_stats.py`, `test_ci_stats.py` | core | |
| `.github/workflows/ci.yml` | core | The gate. Comment header scrubbed. |
| `.github/workflows/frontend.yml`, `backend.yml` | core | |
| `.github/workflows/e2e.yml` | core | Stays opt-in (`E2E_ENABLED`), same as StoreCart. |
| `.github/workflows/ci-trend.yml` | core | |
| `.github/workflows/post-deploy-smoke.yml` | core, trimmed | Keep `/api/health` and `/health`; drop store/storefront probes if any. |
| `.github/workflows/vercel-preview.yml` | core | Manual preview deploy. |
| `.github/workflows/migrate-stores.yml` | StoreCart-only | Per-store Alembic. |
| `AGENTS.md` | rewrite | Short generic version (branch and commit format, no force push, no secrets). No baton, no Jira. |
| `PROJECT-CONTEXT.md` | rewrite | "Your App" placeholder context. |
| `README.md` | rewrite | How to start a project, how to remove each module, how to sync from StoreCart (AC). |
| `LICENSE` | new | MIT, template's own (AC). |
| `docker-compose.yml` | core | Project name default `app`. |
| `package.json` | core | `name` placeholder. |
| `vercel.json` | core, trimmed | Keep the two services and the catch-all; keep `/webhooks/stripe` (billing module); drop `/internal/provisioning`, `/internal/carts`, `/webhooks/stripe-connect`. |
| `scripts/compose-smoke.sh` | core | |
| `scripts/vercel-ignore-build.sh`, `.test.sh` | core | |
| `scripts/export-template.sh` | new | The export itself (lands in StoreCart with this doc). |
| `docs/` | see below | |
| `nextjs-frontend/` | see below | |
| `fastapi_backend/` | see below | |

## docs/

| Path | Class | Notes |
| --- | --- | --- |
| `docs/adr/README.md` | core, trimmed | Index of the exported ADRs plus the ADR template section. |
| `docs/adr/0001` template adoption, `0002` Vercel, `0003` auth, `0004` layering, `0006` Docker, `0007` rate-limit keys, `0008` client generation, `0011` Vercel services | core | Numbers kept so links stay valid; StoreCart wording scrubbed. |
| `docs/adr/0005` per-store DB, `0010` accounts and payments | StoreCart-only | |
| `docs/adr/0009` email with Resend | StoreCart-only | Decision without code; ships when email does. |
| `docs/design/**` | StoreCart-only | UI redesign plan and concepts. |
| `docs/developer/README.md` | rewrite | Index of the exported pages. |
| `getting-started.md`, `architecture.md`, `testing.md`, `local-e2e.md`, `vercel-previews.md`, `security.md`, `e2e-firebase-runbook.md`, `admin-settings.md` | core, trimmed | Store paragraphs removed. |
| `workflow.md` | rewrite | Branch, commit, PR and review flow without Jira. |
| `platform-models.md`, `backend-auth.md`, `backend-totp.md`, `backend-profile.md`, `backend-public-settings.md`, `backend-audit-logs.md`, `backend-admin-users.md`, `backend-organizations.md`, `backend-frontend-seams.md` | core, trimmed | |
| `backend-org-billing.md`, `backend-billing-webhook.md`, `backend-admin-subscriptions.md`, `backend-plan-limits.md`, `backend-admin-analytics.md` | module: billing | Analytics trimmed to users and subscriptions. |
| `modules.md`, `template-sync.md` | new | Module removal recipes; how to pull a `template-candidate` feature from StoreCart (AC). |
| `backend-admin-stores.md`, `backend-checkout.md`, `backend-media.md`, `backend-orders-api.md`, `backend-products-api.md`, `backend-refunds.md`, `backend-store-*.md`, `backend-storefront-*.md`, `backend-stripe-connect.md`, `dashboard-products.md`, `dashboard-store-scope.md`, `storefront-*.md`, `legacy-browser-regressions.md`, `agent-handover.md`, `known-issues.md`, `template-export.md` (this page) | StoreCart-only | |
| `docs/user-guide/**` | StoreCart-only | |

## nextjs-frontend/

### Config and tooling

| Path | Class | Notes |
| --- | --- | --- |
| `package.json`, `package-lock.json` | core, trimmed | `name` placeholder; drop `foundation:*` scripts and `tsx` if unused; Capacitor scripts stay (module: mobile). Lockfile regenerated with `npm install` after the trim. |
| `.env.example` | core | Drop R2, Resend, QStash, Neon, `STORE_DB_*`, `PLATFORM_ROOT_DOMAIN`; keep Stripe (module), Capacitor (module) with placeholders. |
| `AGENTS.md` | core | The Next.js-generated block only. |
| `Dockerfile`, `.dockerignore`, `.prettierrc`, `.prettierignore`, `components.json`, `eslint.config.mjs`, `postcss.config.mjs`, `tailwind.config.ts`, `tsconfig.json`, `vitest.config.ts`, `vitest.setup.ts` | core | ESLint keeps the `@/lib/api/generated*` import ban. |
| `next.config.ts` | core | |
| `openapi-ts.config.ts` | core | |
| `openapi.json`, `src/lib/api/generated/**` | core, regenerated | Regenerated from the trimmed backend, never hand-edited. |
| `playwright.config.ts`, `playwright.local.config.ts`, `playwright.baseline.config.ts` | core | |
| `sentry.*.config.ts`, `src/instrumentation*.ts` | core | |
| `capacitor.config.ts` | module: mobile | Already placeholders (`com.yourcompany.app`); keystore env names documented, no values. |
| `public/icon-*.svg` | core | Generic icons. |
| `scripts/check-openapi-client.mjs`, `dev-clean.cjs`, `dev-kill.cjs`, `ports.cjs`, `e2e-accounts.mjs`, `e2e-build.mjs`, `e2e-env.cjs`, `e2e-local.mjs`, `e2e-start.mjs`, `setup-e2e-accounts.mjs`, `firebase-rest-admin.mjs` | core | The fast e2e setup. |
| `scripts/e2e-stripe-listen.mjs` | module: billing | |
| `scripts/foundation-done-check*.ts` | StoreCart-only | |

### src/app

| Path | Class | Notes |
| --- | --- | --- |
| `layout.tsx`, `page.tsx`, `globals.css`, `error.tsx`, `global-error.tsx`, `loading.tsx`, `not-found.tsx`, `manifest.ts`, `contact/` | core | `page.tsx` is already a generic landing page. |
| `(auth)/**` | core | Login, signup, reset, verify-email. |
| `(admin)/admin/` layout, `page.tsx`, `_components/`, `users/**`, `audit-logs/**`, `settings/`, `seo/`, `organizations/` | core | |
| `(admin)/admin/subscriptions/**`, `analytics/` | module: billing | Analytics trimmed to users and subscriptions. |
| `(admin)/admin/stores/**` | StoreCart-only | |
| `actions/auth-actions.ts`, `user-actions.ts`, `theme-actions.ts`, `font-actions.ts`, `admin/user-actions.ts` | core | |
| `actions/subscription-actions.ts`, `admin/analytics-actions.ts` | module: billing | |
| `actions/admin-store-actions.ts`, `connect-actions.ts`, `onboarding-actions.ts`, `order-actions.ts`, `product-actions.ts`, `product-import-actions.ts`, `store-actions.ts`, `store-settings-actions.ts` | StoreCart-only | |
| `api/auth/clear-session/route.ts`, `api/health/route.ts` | core | |
| `dashboard/layout.tsx`, `page.tsx` | core, trimmed | Drop the store switcher, onboarding gate and orders/products panels; the overview becomes profile, plan and notifications. |
| `dashboard/profile/`, `security/`, `settings/page.tsx` | core | |
| `dashboard/settings/billing/` | module: billing | |
| `dashboard/onboarding/**`, `orders/**`, `products/**`, `settings/store/` | StoreCart-only | |
| `pricing/` | module: billing | |
| `storefront/**`, `storefront-preview/**` | StoreCart-only | |

### src/components

| Path | Class | Notes |
| --- | --- | --- |
| `ui/**`, `providers/**`, `auth/**`, `admin/*` | core | `admin-nav-items.ts` loses the Stores entry. |
| `dashboard/dashboard-header.tsx`, `sidebar.tsx`, `tab-bar.tsx`, `nav-items.ts`, `kpi-strip.tsx`, `profile/`, `overview/panel.tsx`, `permission-notice.tsx`, `refresh-button.tsx`, `styles.ts`, `types.ts` | core, trimmed | Nav keeps Overview, Billing (module), Settings, Profile, Security. |
| `dashboard/billing/**`, `plan-usage-meter.tsx`, `subscription-success-handler.tsx`, `overview/overview-plan-usage.tsx`, `pricing/**` | module: billing | |
| `dashboard/store-switcher.tsx`, `new-store-dialog.tsx`, `hide-on-onboarding.tsx`, `store-setup-state.tsx`, `orders/**`, `products/**`, `settings/connect-payments-panel.tsx`, `settings/store-settings-form.tsx`, `settings/form-page.tsx`, `overview/needs-attention.tsx`, `recent-orders-panel.tsx`, `overview-kpi-strip.tsx`, `defaults.ts`, `fixtures.ts`, `onboarding/**`, `storefront/**` | StoreCart-only | |

### src/lib, config, hooks

| Path | Class | Notes |
| --- | --- | --- |
| `lib/api/server.ts`, `session-rejected.ts`, `account.ts`, `admin-access.ts`, `admin-errors.ts`, `admin-users.ts`, `admin-audit-logs.ts`, `settings.ts` | core | |
| `lib/api/billing.ts`, `plan-prices.ts`, `admin-subscriptions.ts`, `admin-analytics.ts`, `lib/billing-status.ts`, `lib/stripe/**`, `config/subscriptions.ts` | module: billing | |
| `lib/api/admin-stores.ts`, `cart.ts`, `checkout.ts`, `connect.ts`, `onboarding.ts`, `orders.ts`, `products.ts`, `storefront*.ts`, `store-settings.ts`, `stores.ts`, `lib/onboarding/`, `lib/orders/`, `lib/products/`, `lib/store-settings/`, `lib/storefront/`, `lib/stores/` | StoreCart-only | |
| `lib/auth/**`, `lib/firebase/**`, `lib/middleware/**`, `lib/utils/**`, `lib/utils.ts`, `lib/logger.ts` | core | |
| `proxy.ts` | core, trimmed | Keep route protection, rate limiting, security headers; drop the storefront host rewrite and store CSP. |
| `config/site.ts`, `fonts.ts`, `themes.ts`, `currencies.ts` | core | `site.ts` is the single brand place (`NEXT_PUBLIC_APP_NAME`, default "Your App"). |
| `hooks/**` | core | |

### src/__tests__

Unit tests follow their subject: a test of a core file is core, of a billing file is billing, of a store
file is StoreCart-only. `__tests__/unit/db/`, `products/`, `storefront/` and the `scripts/` tests of
`foundation-done-check` are StoreCart-only.

| e2e spec | Class |
| --- | --- |
| `auth.setup.ts`, `helpers/e2e-utils.ts`, `helpers/fixtures.ts` | core |
| `auth`, `account-lifecycle`, `admin`, `dashboard-shell`, `dashboard`, `display-font`, `homepage`, `password-change`, `reauth-dialog`, `session-expiry`, `session-refresh-2fa`, `settings-totp`, `theme-contrast`, `button-contrast`, `touch-targets`, `motion-hygiene`, `currency` | core (store steps removed from `dashboard-shell` and `dashboard`) |
| `billing-management`, `pricing`, `subscription`, `subscription-simple`, `admin-analytics`, `SUBSCRIPTION_TESTS.md` | module: billing |
| `admin-stores`, `connect-onboarding`, `merchant-onboarding`, `new-store`, `orders-management`, `product-import`, `product-management`, `store-settings`, `store-switcher`, `storefront-*`, `helpers/*.py`, `helpers/orders-e2e.ts`, `helpers/products-e2e.ts` | StoreCart-only |

## fastapi_backend/

### Config and tooling

| Path | Class | Notes |
| --- | --- | --- |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | core, trimmed | Name placeholder; drop `boto3` and `boto3-stubs` (R2) and the store-engine TID251 ban; `fail_under` reset to the measured template baseline. Lock and export regenerated. |
| `.env.example` | rewrite | Backend names only (`DATABASE_URL`, `ENVIRONMENT`, Firebase Admin, `BACKEND_INTERNAL_KEY`, Upstash, Sentry, `TOTP_ENCRYPTION_KEY`, Stripe for the module). The file on `main` today is a copy of the frontend one. |
| `.gitignore`, `.dockerignore`, `Dockerfile`, `start.sh`, `watcher.py`, `mypy.ini`, `pytest.ini`, `vercel.json` | core | |
| `CLAUDE.md` | rewrite | Commands, layering, Alembic rules; no Jira or baton. |
| `TEMPLATE_LICENSE.txt` | core | Vinta MIT notice, kept (AC). |
| `alembic.ini`, `alembic_migrations/env.py`, `script.py.mako` | core | |
| `alembic_migrations/versions/0001..0011` | StoreCart-only | Replaced by one generated `0001_baseline.py` from the trimmed models. |
| `alembic_store.ini`, `alembic_store/**` | StoreCart-only | |
| `commands/generate_openapi_schema.py`, `check_openapi_schema.py`, `purge_legacy_e2e_accounts.py` | core | |
| `commands/migrate_stores.py`, `sweep_checkout_orders.py` | StoreCart-only | |

### app/

| Path | Class | Notes |
| --- | --- | --- |
| `main.py` | core, trimmed | Drop `check_provisioning_settings`. |
| `api/auth.py`, `deps.py`, `ids.py`, `me.py`, `admin.py`, `rate_limit.py` | core | |
| `api/merchant.py`, `store_db.py` | StoreCart-only | |
| `api/v1/router.py` | core, trimmed | Includes only the exported routers. |
| `api/v1/health.py`, `auth.py`, `me.py`, `me_export.py`, `notifications.py`, `totp.py`, `admin_users.py`, `admin_audit_logs.py`, `settings.py`, `organizations.py` | core, trimmed | `organizations.py` loses store creation and the store limit; `me_export.py` loses store data; `notifications.py` loses the store scope. |
| `api/v1/org_billing.py`, `webhooks.py`, `admin_subscriptions.py`, `admin_analytics.py` | module: billing | Analytics trimmed to users and subscriptions. |
| `api/v1/admin_stores.py`, `cart.py`, `categories.py`, `checkout.py`, `internal_cart_purge.py`, `internal_provisioning.py`, `media.py`, `order_refunds.py`, `orders.py`, `org_connect.py`, `product_import.py`, `products.py`, `store_retry.py`, `store_settings.py`, `storefront.py`, `storefront_catalogue.py`, `stores.py`, `webhooks_connect.py` | StoreCart-only | |
| `core/base.py`, `config.py`, `database.py`, `db_errors.py`, `db_url.py`, `errors.py`, `firebase.py`, `ids.py`, `logging.py`, `permissions.py`, `platform_schema.py`, `rate_limit.py`, `request_id.py`, `sentry.py`, `slugs.py`, `totp.py` | core, trimmed | `config.py` loses Neon, QStash, store, Connect, `PLATFORM_ROOT_DOMAIN`; `permissions.py` loses `stores.*`. |
| `core/plans.py`, `stripe_admin.py`, `stripe_billing.py`, `stripe_prices.py`, `stripe_signature.py`, `stripe_sync.py`, `stripe_webhook_body.py` | module: billing | |
| `core/qstash_signature.py`, `store_crypto.py`, `stripe_checkout.py`, `stripe_connect.py`, `stripe_refunds.py` | StoreCart-only | |
| `models/__init__.py`, `models/platform/__init__.py` | core, trimmed | Registers only the exported tables. |
| `models/platform/admin_user.py`, `app_setting.py`, `audit_log.py`, `email_template.py`, `enums.py`, `feature_flag.py`, `invitation.py`, `membership.py`, `mixins.py`, `organization.py`, `seo_meta.py`, `url_redirect.py`, `user.py` | core, trimmed | `organization.py` loses the Connect columns; `audit_log.py` loses `store_id`; `user.py` notifications lose the store scope. |
| `models/platform/stripe_event.py` | module: billing | `organization.py` billing columns go with it. |
| `models/platform/store.py`, `stripe_connect_event.py` | StoreCart-only | |
| `repositories/base.py`, `auth.py`, `me.py`, `me_export.py`, `me_preferences.py`, `admin.py`, `admin_users.py`, `audit.py`, `app_settings.py`, `health.py`, `notifications.py`, `organizations.py`, `totp.py` | core, trimmed | |
| `repositories/billing.py`, `org_billing.py`, `admin_subscriptions.py`, `admin_analytics.py` | module: billing | |
| `repositories/admin_stores.py`, `checkout.py`, `connect_events.py`, `merchant.py`, `org_connect.py`, `store_*.py`, `storefront.py` | StoreCart-only | |
| `services/auth.py`, `signin_totp.py`, `totp.py`, `me.py`, `me_export.py`, `me_preferences.py`, `admin_users.py`, `audit.py`, `audit_logs.py`, `health.py`, `notifications.py`, `organizations.py`, `public_settings.py` | core, trimmed | |
| `services/org_billing.py`, `admin_subscriptions.py`, `admin_subscription_sync.py`, `admin_analytics.py`, `plan_limits.py`, `plan_prices.py`, `price_cache.py`, `stripe_webhook.py` | module: billing | `plan_limits.py` keeps only the member limit. |
| `services/admin_stores.py`, `media_uploads.py`, `merchant*.py`, `product_import.py`, `provisioning_readiness.py`, `store_*.py`, `storefront*.py`, `stripe_connect.py` | StoreCart-only | |

### tests/

Tests follow their subject, as in the frontend. `tests/conftest.py`, `_worker_db.py`, `pg_scaffold.py`,
`fakes.py`, `fakes_admin_users.py`, `fakes_billing.py` (module), `fakes_admin_subscriptions.py` (module),
`fakes_admin_analytics.py` (module) and `qstash_tokens.py` (StoreCart-only) are the shared fixtures.
`fakes_admin_stores.py`, `fakes_connect.py`, `fakes_provisioning.py`, `isolation_world.py` and every
`test_store*`, `test_storefront*`, `test_cart*`, `test_checkout*`, `test_order*`, `test_product*`,
`test_merchant*`, `test_tenant*`, `test_internal*`, `test_media*`, `test_org_connect*`, `test_stripe_connect*`,
`test_qstash*`, `test_r2*`, `test_admin_stores*` file is StoreCart-only.

## Build approach

1. `scripts/export-template.sh <target-dir>` copies the core and module paths from a clean `git archive` of
   `main`, skips the StoreCart-only paths, and runs the brand and Jira-key scrub
   (`StoreCart` → `Your App`, `storecart` → `app`, `KAN-\d+` references removed from comments; 61 and 403
   hits today).
2. The *trimmed* files are then edited by hand in the export (not in StoreCart): routers, models, nav items,
   dashboard shell, proxy, config, `.env.example`s, docs. This is the sized part of the work.
3. Regenerate: `uv lock`, `requirements.txt`, the Alembic baseline (`alembic revision --autogenerate` against
   a throwaway Postgres, then `alembic check`), `openapi.json`, the TypeScript client, `package-lock.json`.
4. Verify with placeholder env only: `npm ci && npm run lint && npm run typecheck && npm run test:unit &&
   npm run build`; `uv sync && uv run ruff check . && uv run mypy && uv run pytest --cov`;
   `scripts/compose-smoke.sh all`.
5. Secret scan of the whole export (gitleaks or trufflehog over the tree, plus a grep for the owner's
   project ids, emails and domains) before `git init`.
6. Fresh history: `git init`, one commit, push to the empty public repo **after the owner has seen the
   final file list**. Then: template flag, `CI gate` branch protection, Dependabot; add the Jira label
   `template-candidate` to KAN-145 and document the sync procedure in `docs/developer/template-sync.md`.

## Open decisions for the owner

1. **Organisations and memberships** stay as core (billing is per organisation, invitations exist). Cutting
   them would make the template single-user; recommend keeping.
2. **Media uploads (R2)** are tied to products, so they are StoreCart-only. They could later be an optional
   module if a project needs file uploads; not now.
3. **Email**: nothing to export. Options: ship without email and say so in the README (recommended, matches
   the code); or a new story adds a minimal Resend sender to StoreCart first and the template picks it up
   as a `template-candidate`.
4. **Admin analytics** counts stores and orders. Recommend keeping it in the billing module, trimmed to
   signups and subscriptions, rather than cutting it.
5. **ECC plugin reference** in `.claude/settings.json`: drop (recommended) or keep for projects that use it.
6. **Fresh Alembic baseline** instead of the 11 StoreCart revisions: recommend yes (fresh history anyway).
7. **Size**: steps 2 to 4 are several days of work for one agent and touch most of the exported files.
   The export runs from a fixed `main` SHA, so StoreCart work continues in parallel.
