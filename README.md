# SaaS Boilerplate - Next.js 16

A production-ready SaaS boilerplate built with Next.js 16, React 19, Firebase Auth, Stripe, and comprehensive testing.

## ⚡ Quick Start

```bash
# Install dependencies
npm install

# Setup environment
cp .env.example .env
# Edit .env with your credentials (see docs/developer/getting-started.md)

# Start development
npm run dev
```

Visit `http://localhost:3000` (the default; set `PORT` to change it, see
[Running in parallel](docs/developer/getting-started.md#running-in-parallel))

📖 **[Read the developer docs](docs/developer/README.md)** for setup, architecture, testing and troubleshooting.

## ✨ Features

### Customer Features

- 🔐 **Authentication** - Email/password + OAuth (Google, GitHub)
- 👤 **User Dashboard** - Stats, activity, notifications
- ⚙️ **Profile & Settings** - Customizable preferences
- 🔒 **Security** - Password change, 2FA, login history
- 💳 **Subscriptions** - Stripe integration with 3 tiers

### Admin Features

- 📊 **Admin Dashboard** - User metrics, revenue, analytics
- 👥 **User Management** - Search, filter, edit, delete users
- 💰 **Subscription Management** - View, cancel, refund subscriptions
- 📈 **Analytics** - Charts, reports, insights
- 🔍 **SEO Tools** - Meta tags, redirects
- 🛠️ **Settings** - Feature flags, email templates
- 📝 **Audit Logs** - Track all admin actions

### Developer Features

- ⚡ Next.js 16 App Router with Server Components
- 🎨 shadcn/ui + Tailwind CSS
- 🗄️ FastAPI backend + PostgreSQL
- 🧪 Vitest + Playwright testing
- 📱 Mobile-ready (PWA + Capacitor)
- 🚀 Vercel-optimized

## 🏗️ Tech Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS v4
- **Backend:** Next.js API Routes, Server Actions calling the FastAPI backend
- **Database:** PostgreSQL
- **Auth:** Firebase Authentication
- **Payments:** Stripe
- **Testing:** Vitest, Playwright, React Testing Library
- **Mobile:** Capacitor v6

## 📚 Documentation

- **[Environment Variables](#environment-variables)** - Required configuration
- **[Developer documentation](docs/developer/README.md)** - Setup, architecture, workflow, testing, security, known issues
- **[User guide](docs/user-guide/README.md)** - Using StoreCart
- **[Architecture decisions](docs/adr/README.md)** - ADR-001 to ADR-011

## 🔑 Environment Variables

```env
# Database
DATABASE_URL="postgresql://..."

# Firebase
NEXT_PUBLIC_FIREBASE_API_KEY="..."
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN="..."
NEXT_PUBLIC_FIREBASE_PROJECT_ID="..."
FIREBASE_PROJECT_ID="..."
FIREBASE_CLIENT_EMAIL="..."
FIREBASE_PRIVATE_KEY="..."

# Stripe
STRIPE_SECRET_KEY="sk_test_..."
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY="pk_test_..."
STRIPE_WEBHOOK_SECRET="whsec_..."
STRIPE_PRICE_ID_PRO_MONTHLY="price_..."
STRIPE_PRICE_ID_PRO_YEARLY="price_..."
```

See [getting-started.md](docs/developer/getting-started.md) for detailed setup instructions.

## 🚀 Commands

```bash
npm run dev              # Start development server
npm run build            # Build for production
npm run start            # Start production server
npm run lint             # Run ESLint
npm run test             # Run all tests
npm run test:unit        # Run unit tests
npm run test:e2e         # Run E2E tests
```

## 🐳 Local development: Docker Compose or plain uv/npm

Docker is for local development and CI only (ADR-006); Vercel never runs these images.

### Option A: Docker Compose (one command)

Requires Docker with Compose v2. From the repo root:

```bash
docker compose up -d --build     # first run builds the images
docker compose ps                # wait until every service is "healthy"
docker compose exec backend alembic upgrade head   # apply migrations (never run automatically)
docker compose down -v           # stop and delete containers and volumes
```

| Service | URL / port | Healthcheck |
| --- | --- | --- |
| `db` (Postgres 16) | `localhost:5432`, user `postgres`, password `password`, db `storecart` | `pg_isready` |
| `test_db` (Postgres 16, in-memory) | `localhost:5434`, `test` / `test` / `test` | `pg_isready` |
| `redis` | `localhost:6379` | `redis-cli ping` |
| `backend` (FastAPI, `start.sh` with watcher) | http://localhost:8000 (`/health`, `/docs`) | `GET /health` |
| `frontend` (Next.js dev) | http://localhost:3000 | `GET /api/health` |

Notes:

- All credentials are fake and local. To change ports or passwords, copy [`.env.example`](.env.example) to `.env`
  (git-ignored). Real secrets (Firebase, Stripe, Resend and so on) are not part of the compose file; put them in
  `nextjs-frontend/.env.local` only if you need those features.
- To run a second checkout in parallel, set `COMPOSE_PROJECT_NAME` and the host ports in `.env`, and `PORT`,
  `E2E_PORT` and `BACKEND_PORT` for the apps; see
  [Running in parallel](docs/developer/getting-started.md#running-in-parallel).
- The backend runs with `ENVIRONMENT=local`, which disables rate limiting. Production rate limiting talks to Upstash
  over HTTP (ADR-007); the local Redis speaks the Redis protocol only and does not provide an Upstash REST endpoint,
  so it backs local Redis use and future features, not the rate limiter.
- Backend tests can use the test database from the host: set `DATABASE_URL=postgresql+asyncpg://test:test@localhost:5434/test` and run `uv run pytest` in `fastapi_backend/`.
- Source is bind-mounted, so edits hot-reload. Dependencies live in the images and named volumes; after changing `package.json` or `pyproject.toml`, run `docker compose down -v` and then `docker compose up -d --build`.
- In the backend container the watcher cannot regenerate the TypeScript client (no Node there); run
  `npm run generate:client` on the host after API changes.

### Option B: plain uv and npm

Requires Node 22.12+, [uv](https://docs.astral.sh/uv/) and a Postgres you run yourself (for example
`docker compose up -d db`).

```bash
# Backend (terminal 1)
cd fastapi_backend
cp .env.example .env        # points DATABASE_URL at localhost:5432
uv sync
uv run alembic upgrade head
./start.sh                  # FastAPI with reload plus the watcher, on :8000 (BACKEND_PORT to change)

# Frontend (terminal 2)
cd nextjs-frontend
cp .env.example .env.local  # BACKEND_API_URL=http://127.0.0.1:8000
npm ci
npm run dev                 # :3000 (PORT to change)
```

## 🪝 Pre-commit hooks

The repo root has a [`.pre-commit-config.yaml`](.pre-commit-config.yaml) (adapted from the
vintasoftware/nextjs-fastapi-template). On every commit it checks only the staged files:

| Area | Hooks |
| --- | --- |
| `fastapi_backend/` | ruff lint (`--fix`), ruff format, mypy, `requirements.txt` kept in sync with `uv.lock`, `openapi.json` freshness check |
| `nextjs-frontend/` | eslint, prettier (`--write`), `tsc --noEmit` |
| Whole repo | large files, merge conflicts, private keys, byte-order marks |

**Prerequisites:** Node 22.12+ (22 or 24), [uv](https://docs.astral.sh/uv/), and `sh` on your `PATH`
(on Windows, run from Git Bash). Install the dependencies first, because the hooks use them:

```bash
(cd nextjs-frontend && npm ci)
(cd fastapi_backend && uv sync)
```

**Install the hooks** (once per clone, from the repo root):

```bash
uvx pre-commit install                # or: cd fastapi_backend && uv run pre-commit install
uvx pre-commit run --all-files        # optional: run every hook against the whole repo
```

Notes:

- Hooks that rewrite files (ruff `--fix`/format, prettier, the `requirements.txt` sync) fail the
  commit when they change something. Review the changes, `git add` them and commit again.
- If you change `fastapi_backend/pyproject.toml`, run `uv lock` first; the hook regenerates
  `requirements.txt` with `uv export --frozen --no-dev --no-hashes`.
- Two hooks keep the API contract current (ADR-008): `openapi-schema-check` compares
  `nextjs-frontend/openapi.json` with the backend, and `openapi-client-check` compares
  `nextjs-frontend/src/lib/api/generated` with that schema. To fix a failure, run
  `uv run python -m commands.generate_openapi_schema` in `fastapi_backend/`, then
  `npm run generate:client` in `nextjs-frontend/`, and commit both.
- `--all-files` also reports existing lint/type issues in code nobody has touched yet. Commits
  are only checked against the files they change.
- To skip the hooks in an emergency: `git commit --no-verify`.

## 🏢 Project Structure

```
src/
├── app/
│   ├── (auth)/          # Login, signup, password reset
│   ├── (admin)/admin/   # Admin portal (8 pages)
│   ├── dashboard/       # Customer dashboard
│   ├── pricing/         # Smart pricing page
│   ├── contact/         # Contact form
│   ├── actions/         # Server Actions
│   └── api/             # API routes + webhooks
├── components/
│   ├── ui/              # shadcn/ui components
│   ├── auth/            # Auth forms
│   ├── pricing/         # Pricing components
│   └── providers/       # React providers
├── lib/
│   ├── firebase/        # Firebase setup
│   ├── stripe/          # Stripe integration
│   ├── services/        # Audit logging, etc.
│   └── utils/           # Utilities
└── proxy.ts             # Middleware (auth, rate limiting)
```

## 🛠️ Common Issues

### Lock File Error

```bash
npm run dev:kill    # Kills processes and removes lock
npm run dev         # Start fresh
```

### Module Not Found

This project uses **npm** (not pnpm):

```bash
rm -rf node_modules package-lock.json
npm install
```

See the Troubleshooting section of [getting-started.md](docs/developer/getting-started.md) for more.

## 📦 What's Included

### Pages

- Landing page
- Authentication (login, signup, password reset, email verification)
- Customer dashboard (profile, settings, security)
- Admin portal (8 pages: dashboard, users, subscriptions, analytics, SEO, settings, audit logs)
- Pricing page with smart CTAs
- Contact form

### Database Models

- User, UserSettings, LoginHistory, Notification
- AdminUser, AuditLog
- Subscription data (via Stripe)
- SEOMeta, URLRedirect, AppSettings, FeatureFlag, EmailTemplate

### Features Implemented

- ✅ Complete authentication flow
- ✅ Customer dashboard with analytics
- ✅ Full admin portal with 8 pages
- ✅ Subscription management with Stripe
- ✅ Smart pricing page (detects auth state)
- ✅ Login history tracking
- ✅ Audit logging for admin actions
- ✅ Email verification enforcement
- ✅ Password change functionality
- ✅ Data export (GDPR compliance)
- ✅ Account deletion
- ✅ Rate limiting middleware
- ✅ Security headers
- ✅ SEO management tools

## 📄 License

MIT

## 🤝 Contributing

Contributions welcome! Please read the [developer docs](docs/developer/README.md) first.

## 📞 Support

For detailed documentation, setup instructions, and troubleshooting, see the **[developer docs](docs/developer/README.md)**.
