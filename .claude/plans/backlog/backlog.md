# StoreCart backlog

Source: .claude/plans/storecart-plan.md (nextjs-frontend + fastapi_backend from vintasoftware/nextjs-fastapi-template, multi-tenant commerce SaaS)

**21 epics, 88 stories.**

| Epic | Phase | Release | Stories |
|---|---|---|---|
| E1 Monorepo restructure | A | Foundation | 6 |
| E2 Backend foundation (FastAPI) | B | Foundation | 7 |
| E3 Platform data and authentication | C | Foundation | 6 |
| E4 Organisation billing (Stripe Billing) | D | Foundation | 4 |
| E5 Platform admin | E | Foundation | 5 |
| E6 Frontend decoupling | F | Foundation | 1 |
| E7 Multi-tenancy core (one database per store) | G | Multi-tenancy | 7 |
| E8 Merchant onboarding and team | G | Multi-tenancy | 5 |
| E9 Storefront routing and media | G | Multi-tenancy | 3 |
| E10 Stripe Connect payments | 1 | Commerce v1 | 3 |
| E11 Catalogue and inventory | 1 | Commerce v1 | 5 |
| E12 Storefront and cart | 1 | Commerce v1 | 3 |
| E13 Orders, fulfilment and refunds | 1 | Commerce v1 | 4 |
| E14 Store settings: shipping, tax and plan limits | 1 | Commerce v1 | 3 |
| E15 Custom domains | 2 | Commerce v2 | 2 |
| E16 Discounts and coupons | 2 | Commerce v2 | 2 |
| E17 Shipping zones and Stripe Tax | 2 | Commerce v2 | 3 |
| E18 Shopper accounts | 2 | Commerce v2 | 2 |
| E19 Returns, abandoned carts and analytics | 2 | Commerce v2 | 3 |
| E20 VevoCart parity features | 3 | Commerce v3 | 11 |
| E21 Marketplace mode and merchant mobile app | Later | Future | 3 |

## Release: Foundation

### E1 Monorepo restructure (phase A)

Split the repository into nextjs-frontend/ (Next.js) and fastapi_backend/ (FastAPI, from vintasoftware/nextjs-fastapi-template) that build, test and deploy independently.

- **E1.1 Finalise move of Next.js app into nextjs-frontend/** `frontend, infra`
  - [ ] The move is committed so Git records renames and history is preserved
  - [ ] Root .gitignore covers nested paths (.next, node_modules, logs, playwright-report, test-results, coverage, .venv, __pycache__) and the stale root .next is removed
  - [ ] npm ci, npm run typecheck and npm run build pass inside nextjs-frontend/; .claude/CLAUDE.md paths are updated
- **E1.2 Docker Compose for local development (from template)** `infra`
  - [ ] docker-compose.yml adapted from the template starts Postgres, test Postgres, Redis, backend (start.sh with watcher) and frontend, all with healthchecks
  - [ ] Root README explains both the Compose and the plain uv/npm workflows
- **E1.3 Path-filtered CI workflows for frontend and backend** `infra`
  - [ ] frontend.yml runs only when nextjs-frontend/** changes
  - [ ] backend.yml runs only when fastapi_backend/** changes (adapted from the template's workflows)
  - [ ] Both workflows pass on the restructure PR
- **E1.4 Two Vercel projects and Playwright config fix** `frontend, infra`
  - [ ] Frontend Vercel project is rooted at nextjs-frontend; backend Vercel project is rooted at fastapi_backend using api/index.py
  - [ ] Preview deployments use a separate database from production
  - [ ] playwright.config.ts webServer uses npm run dev instead of the stale pnpm dev
- **E1.5 ADR-001: architecture decisions** `docs`
  - [ ] docs/adr/ records decisions D1-D23 from .claude/plans/storecart-plan.md
  - [ ] Covers template adoption, Vercel backend, Firebase kept, hey-api client and Resend
- **E1.6 Pre-commit hooks (from template)** `infra`
  - [ ] .pre-commit-config.yaml adapted from the template runs ruff (lint + format) and mypy for fastapi_backend, and eslint/prettier/tsc for nextjs-frontend
  - [ ] Hooks keep requirements.txt in sync with uv.lock and check that the OpenAPI client is up to date
  - [ ] README explains how to install the hooks

### E2 Backend foundation (FastAPI) (phase B)

Adapt the template backend into a production-ready StoreCart API with configuration, logging, errors, health checks, rate limiting, a typed API contract and Vercel deployment.

- **E2.1 Adapt template backend for StoreCart** `backend`
  - [ ] Example Item model/routes/migrations, fastapi-users and fastapi-mail are removed and the project is renamed to StoreCart
  - [ ] Outdated pins (ruff, fastapi, pytest-asyncio) are upgraded and code is organised into app/core, app/api/v1, services and repositories
  - [ ] uv run pytest, ruff check and mypy pass in CI
- **E2.2 Configuration, structured logging and error envelope** `backend`
  - [ ] Settings extend the template's pydantic-settings config and fail fast on missing secrets
  - [ ] All errors return {success:false, error} with no stack traces or internal details
  - [ ] JSON logs with a request ID replace print(); CORS is restricted to known origins
- **E2.3 Health endpoints and hardened Dockerfile** `backend, infra`
  - [ ] /health returns 200; /ready checks database and Redis
  - [ ] Dockerfile uses a pinned uv image instead of curl | sh and runs as a non-root user
- **E2.4 OpenAPI schema and generated TypeScript client** `backend, frontend`
  - [ ] commands/generate_openapi_schema (and watcher.py in dev) writes nextjs-frontend/openapi.json
  - [ ] nextjs-frontend generates a typed fetch client with @hey-api/openapi-ts, wrapped server-only and forwarding the Firebase session
  - [ ] CI and pre-commit fail when the generated client is out of date
- **E2.5 Redis-backed rate limiting** `backend, security`
  - [ ] Auth, API and webhook limits match the boilerplate's existing configuration
  - [ ] Limits use Upstash Redis so they hold across serverless instances
  - [ ] Exceeding a limit returns 429 with rate-limit headers
- **E2.6 Sentry integration and backend conventions doc** `backend, docs`
  - [ ] Unhandled errors reach Sentry with request context
  - [ ] fastapi_backend/CLAUDE.md documents commands, layering (routers > services > repositories) and test conventions
- **E2.7 Backend deployment on Vercel** `backend, infra`
  - [ ] Preview and production deployments of fastapi_backend work via api/index.py, with secrets from Vercel environment variables
  - [ ] The engine uses NullPool with Neon pooled endpoints; platform migrations run on production deploy only
  - [ ] Production deploys go through a release workflow and /health is smoke-tested after each deploy

### E3 Platform data and authentication (phase C)

Port the boilerplate's user, auth and notification features to FastAPI on the final platform data model, with the frontend calling the API.

- **E3.1 Platform database models and Alembic baseline** `backend, db`
  - [ ] A new Alembic baseline replaces the template's user and item migrations
  - [ ] SQLAlchemy models cover the boilerplate's 11 models plus Organization, Membership, Invitation and the Store registry, with billing on Organization
  - [ ] alembic upgrade head succeeds on an empty database
- **E3.2 Firebase session authentication (replaces fastapi-users)** `backend, security`
  - [ ] POST /v1/auth/session verifies the ID token, syncs the user, records login history and returns a session cookie
  - [ ] Requests are authenticated with verify_session_cookie(check_revoked=True)
  - [ ] DELETE /v1/auth/session revokes the session
- **E3.3 Profile, settings and account endpoints** `backend`
  - [ ] Profile, avatar, settings, login history, data export and account deletion are available under /v1/me
  - [ ] Each endpoint has integration tests
- **E3.4 Two-factor authentication (TOTP)** `backend, security`
  - [ ] Users can enrol, verify and disable TOTP
  - [ ] Secrets are never returned after enrolment
- **E3.5 Notifications endpoints** `backend`
  - [ ] List, mark read, mark all read and delete notifications for the current user only
- **E3.6 Frontend auth, profile and notifications use the API** `frontend`
  - [ ] auth, user and notification server actions call the API client instead of Prisma
  - [ ] Existing e2e tests auth.spec, dashboard.spec and session-expiry.spec pass

### E4 Organisation billing (Stripe Billing) (phase D)

Merchants pay the platform a subscription per organisation, managed entirely by the backend.

- **E4.1 Subscription plans config with limits** `backend, payments`
  - [ ] Free, Pro and Enterprise plans define store, product and staff limits
  - [ ] Each plan has platform_fee_bps = 0 so a per-order fee can be enabled later
- **E4.2 Organisation billing endpoints** `backend, payments`
  - [ ] Checkout, portal, plan change, cancel, resume, invoices and payment methods are scoped to an organisation
  - [ ] Only OWNER and ADMIN roles can manage billing
- **E4.3 Stripe Billing webhook with idempotency** `backend, payments, security`
  - [ ] Signature is verified on the raw body
  - [ ] Each Stripe event is processed at most once
  - [ ] Subscription status on the organisation stays in sync
- **E4.4 Frontend billing and pricing pages use the API** `frontend, payments`
  - [ ] Billing and pricing pages call the API
  - [ ] subscription and billing-management e2e tests pass

### E5 Platform admin (phase E)

Port the boilerplate's admin area to FastAPI with permission checks and audit logging.

- **E5.1 Admin permissions dependency and audit logging** `backend, security`
  - [ ] require_admin(permissions) rejects users without the required permission
  - [ ] Every admin change writes an audit log entry
- **E5.2 Admin users API** `backend`
  - [ ] List, detail, update, delete, grant/revoke admin, ban/unban, stats and send notification
- **E5.3 Admin subscriptions API** `backend, payments`
  - [ ] Subscription list, stats, revenue, refunds, free grants and Stripe sync
- **E5.4 Admin settings, SEO and audit API** `backend`
  - [ ] App settings, feature flags, email templates, SEO meta, redirects, audit logs and system stats
- **E5.5 Admin and dashboard pages use the API** `frontend`
  - [ ] The 10 pages that query the database directly now call the API
  - [ ] admin.spec e2e passes

### E6 Frontend decoupling (phase F)

The frontend holds no database, Stripe secret or Firebase Admin credentials.

- **E6.1 Remove Prisma and server secrets from the frontend** `frontend, security`
  - [ ] nextjs-frontend/prisma, src/lib/db and server-side Stripe/Firebase Admin code are removed
  - [ ] @prisma/client, prisma, stripe and firebase-admin are no longer frontend dependencies
  - [ ] An ESLint rule blocks reintroducing them and the frontend has no DATABASE_URL

## Release: Multi-tenancy

### E7 Multi-tenancy core (one database per store) (phase G)

Each store gets its own Postgres database, created automatically, kept on the same schema version, and reachable only by members of its organisation.

- **E7.1 Merchant authorisation dependency** `backend, security`
  - [ ] require_merchant(store_id, roles) returns user, organisation, store and role
  - [ ] A store from another organisation returns 404
  - [ ] Unit tests cover every role, missing membership and suspended stores
- **E7.2 Encrypted store connection strings** `backend, security`
  - [ ] Connection strings are stored with AES-256-GCM using a key validated at startup
  - [ ] Tampered data or a wrong key fails safely
  - [ ] Plaintext connection strings never appear in logs
- **E7.3 Store database session factory** `backend, db`
  - [ ] get_store_session(store_id) returns an async session for that store only
  - [ ] Uses NullPool with Neon pooled endpoints (serverless-safe), with no long-lived pools
  - [ ] A ruff banned-import rule stops store engines being created anywhere else
- **E7.4 Database provisioner (local Postgres and Neon)** `backend, db, infra`
  - [ ] Local provider creates a database on the Docker Postgres
  - [ ] Neon provider creates the database through the Neon API
  - [ ] Both implement the same interface and are covered by tests
- **E7.5 Store provisioning background job** `backend, infra`
  - [ ] Creating a store enqueues QStash steps: create database, run migrations, mark ready
  - [ ] Each step is idempotent, fits within one Vercel function invocation, retries, and sets status failed on error
- **E7.6 Migration runner for all store databases** `backend, db`
  - [ ] commands/migrate_stores applies pending store migrations to every ready store in batches
  - [ ] Stops on the first failure and records each store's schema version
  - [ ] Runs from GitHub Actions on deploy, never inside a request; migrations stay compatible with the previous code version
- **E7.7 Tenant isolation test suite** `backend, security`
  - [ ] Two organisations with several stores each, on real separate databases
  - [ ] Tests prove no user can read or write another organisation's store data

### E8 Merchant onboarding and team (phase G)

Merchants can sign up, create organisations and stores, invite staff and switch between stores.

- **E8.1 Organisation and store APIs** `backend`
  - [ ] Create, list and update organisations and stores
  - [ ] Store slugs are validated for format, uniqueness and reserved words (www, admin, api, app)
- **E8.2 Merchant onboarding flow** `frontend`
  - [ ] Sign-up leads to creating an organisation and first store
  - [ ] A status screen shows provisioning progress until the store is ready
  - [ ] e2e covers sign-up to a ready store
- **E8.3 Merchant dashboard shell and store switcher** `frontend`
  - [ ] Dashboard layout scoped to the selected store
  - [ ] Merchants with several stores can switch between them
- **E8.4 Team invitations and roles** `backend, frontend, security`
  - [ ] Owners and admins invite by email; links expire after 7 days and work once
  - [ ] STAFF cannot access team or billing settings
- **E8.5 Platform admin: merchants and stores** `frontend, backend`
  - [ ] Admins see organisations and stores with database status and schema version
  - [ ] Admins can suspend and unsuspend stores and re-run provisioning or migrations

### E9 Storefront routing and media (phase G)

Each store is reachable on its own subdomain and can upload product images.

- **E9.1 Wildcard subdomain routing** `frontend, infra`
  - [ ] {slug}.yourplatform.com rewrites to the store's storefront via proxy.ts
  - [ ] Unknown or suspended stores return 404
  - [ ] Works locally on *.localhost
- **E9.2 Public storefront store lookup API** `backend`
  - [ ] GET /v1/storefront/{slug} returns public store details only
  - [ ] Responses are cacheable
- **E9.3 Image uploads to Cloudflare R2** `backend, security`
  - [ ] Backend issues presigned uploads under stores/{id}/
  - [ ] Only allowed image types and sizes are accepted

## Release: Commerce v1

### E10 Stripe Connect payments (phase 1)

Shoppers pay merchants directly through Stripe Connect, with merchants as the seller of record.

- **E10.1 Stripe Connect onboarding per organisation** `backend, frontend, payments`
  - [ ] Merchants complete Stripe-hosted onboarding
  - [ ] account.updated keeps charges and payouts status in sync
  - [ ] Checkout is blocked until charges are enabled
- **E10.2 Checkout session on the merchant's connected account** `backend, payments`
  - [ ] Direct charges on the merchant's account with no application fee
  - [ ] Fee code path exists but is controlled by platform_fee_bps (0)
  - [ ] Order totals are calculated only on the server in minor units
- **E10.3 Connect webhook handler** `backend, payments, security`
  - [ ] Separate endpoint and signing secret from Stripe Billing
  - [ ] Events are routed to the right store via metadata and connected account
  - [ ] Each event is processed at most once

### E11 Catalogue and inventory (phase 1)

Merchants can create and manage products, variants, categories and stock.

- **E11.1 Product, variant and option data model** `backend, db`
  - [ ] Store schema has products, variants (SKU, price, compare-at price, weight, stock), options and option values
  - [ ] Draft and active statuses with unique slugs
- **E11.2 Nested categories and product images** `backend, frontend`
  - [ ] Categories can be nested and ordered
  - [ ] Products have ordered images stored in R2
- **E11.3 Inventory with oversell protection** `backend`
  - [ ] Stock is decremented atomically when an order is paid
  - [ ] Concurrent checkouts cannot oversell; an oversold order is flagged
- **E11.4 Merchant product management screens** `frontend`
  - [ ] Product list with search and filters
  - [ ] Product editor with variants, images and categories
- **E11.5 Product CSV import** `backend, frontend`
  - [ ] Merchants can import products from CSV with validation errors reported per row

### E12 Storefront and cart (phase 1)

Shoppers can browse a store, add items to a cart and start checkout.

- **E12.1 Storefront theme pages** `frontend`
  - [ ] Home, category, product and search pages for one well-designed theme
  - [ ] Pages are cached and revalidated per store
  - [ ] Per-store SEO metadata
- **E12.2 Server-side cart** `backend, frontend`
  - [ ] Cart is keyed by a store-scoped cookie
  - [ ] Prices and stock are re-checked on the server every time
- **E12.3 Checkout handoff from cart** `backend, frontend, payments`
  - [ ] Creates a pending order and redirects to Stripe Checkout
  - [ ] The order is confirmed only by the webhook, never by the return page

### E13 Orders, fulfilment and refunds (phase 1)

Merchants can manage orders from payment to delivery, issue refunds, and customers receive emails.

- **E13.1 Order model with snapshots and status flow** `backend, db`
  - [ ] Order items snapshot name, price and tax at purchase time
  - [ ] Status flow pending > paid > fulfilled > cancelled/refunded
- **E13.2 Merchant order management** `frontend, backend`
  - [ ] Order list and detail pages
  - [ ] Manual fulfilment with tracking number
- **E13.3 Full and partial refunds** `backend, payments`
  - [ ] Merchants can refund fully or partially through the connected account
  - [ ] Order and payment status update from the refund webhook
- **E13.4 Transactional emails** `backend`
  - [ ] Order confirmation, shipped notice and new-order alert via Resend
  - [ ] Templates are scoped per store with a platform default

### E14 Store settings: shipping, tax and plan limits (phase 1)

Basic shipping and tax so a store can sell, and plan limits enforced.

- **E14.1 Flat-rate and free-over-threshold shipping** `backend, frontend`
  - [ ] Merchants set a flat rate and optional free-shipping threshold
  - [ ] Shipping is included in server-side totals
- **E14.2 Manual tax rate per store** `backend, frontend`
  - [ ] Merchants set a tax rate and whether prices include tax
  - [ ] Tax is included in server-side totals
- **E14.3 Enforce subscription plan limits** `backend`
  - [ ] Store, product and staff limits are enforced on create
  - [ ] Clear upgrade message when a limit is reached

## Release: Commerce v2

### E15 Custom domains (phase 2)

Merchants can serve their store on their own domain with automatic SSL.

- **E15.1 Add and verify a custom domain** `backend, frontend, infra`
  - [ ] Domain is added through the Vercel Domains API
  - [ ] Merchant sees the required DNS records and verification status
  - [ ] SSL is issued automatically once verified
- **E15.2 Route custom domains to the right store** `frontend`
  - [ ] Requests on a verified domain render that store
  - [ ] Unverified domains return 404

### E16 Discounts and coupons (phase 2)

Merchants can run promotions.

- **E16.1 Coupons** `backend, frontend`
  - [ ] Percentage, fixed amount and free shipping coupons
  - [ ] Minimum order, usage limits and expiry
- **E16.2 Automatic discounts** `backend, frontend`
  - [ ] Discounts apply without a code based on cart rules
  - [ ] Quantity-based discounts (VevoCart reference)

### E17 Shipping zones and Stripe Tax (phase 2)

Accurate shipping and tax for stores selling to several regions.

- **E17.1 Shipping zones and rates** `backend, frontend`
  - [ ] Zones by country and state
  - [ ] Rates by weight or order total
- **E17.2 Stripe Tax on connected accounts** `backend, payments`
  - [ ] Tax is calculated by Stripe Tax at checkout
  - [ ] Manual tax rate remains as a fallback
- **E17.3 Live carrier rates (optional)** `backend`
  - [ ] Rates from an aggregator such as Shippo or EasyPost

### E18 Shopper accounts (phase 2)

Shoppers can sign in to a store to see orders and save addresses.

- **E18.1 Store-scoped shopper login by email code** `backend, frontend, security`
  - [ ] Shopper accounts belong to one store and are separate from merchant Firebase logins
  - [ ] Codes expire and are rate limited
- **E18.2 Order history and saved addresses** `frontend, backend`
  - [ ] Signed-in shoppers see their past orders
  - [ ] Shoppers can save and reuse addresses

### E19 Returns, abandoned carts and analytics (phase 2)

Operational tools merchants need once they have regular sales.

- **E19.1 Returns (RMA)** `backend, frontend`
  - [ ] Shoppers request a return; merchants approve, receive and refund
- **E19.2 Abandoned cart emails** `backend`
  - [ ] Email sent after a configurable delay to shoppers who left an email
- **E19.3 Merchant analytics dashboard** `frontend, backend`
  - [ ] Sales, orders and top products over time

## Release: Commerce v3

### E20 VevoCart parity features (phase 3)

Features from VevoCart, built in order of merchant demand.

- **E20.1 Gift cards** `backend, frontend`
  - [ ] Issue, sell and redeem gift cards with balances
- **E20.2 Loyalty points** `backend, frontend`
  - [ ] Earn and redeem points on orders
- **E20.3 Bundle promotions** `backend, frontend`
  - [ ] Discounted bundles of selected products
- **E20.4 Product kits (build to order)** `backend, frontend`
  - [ ] Kits made of selectable component products
- **E20.5 Wholesale price lists** `backend, frontend`
  - [ ] Customer-group pricing
- **E20.6 Multi-currency display** `backend, frontend`
  - [ ] Prices shown in the shopper's currency
- **E20.7 Product reviews** `backend, frontend`
  - [ ] Shoppers review purchased products; merchants moderate
- **E20.8 Blog and content pages** `backend, frontend`
  - [ ] Merchants publish pages and blog posts
- **E20.9 Faceted search** `backend, frontend`
  - [ ] Filter by attributes, price and category; Postgres full-text first
- **E20.10 Google Merchant Center and Meta catalogue feeds** `backend`
  - [ ] Product feeds generated per store
- **E20.11 Multi-language storefront** `frontend, backend`
  - [ ] Store content in several languages

## Release: Future

### E21 Marketplace mode and merchant mobile app (phase Later)

Longer-term options, not yet scheduled.

- **E21.1 Marketplace mode with vendors and split payouts** `backend, payments`
  - [ ] Several vendors per store with payouts through Stripe Connect (VevoCart 6.2 reference)
- **E21.2 Merchant mobile app** `frontend`
  - [ ] Order and product management app built on the existing Capacitor setup
- **E21.3 Public API and webhooks for merchants** `backend`
  - [ ] Merchants can integrate through a documented API and webhooks
