# PROJECT-CONTEXT

## Project
StoreCart — a multi-merchant commerce SaaS. Merchants sign up, create organisations with several
stores, and sell through their own storefronts (subdomains, later custom domains). Each store has
its own Postgres database.

## Tech stack
- Frontend: Next.js 16 (`nextjs-frontend/`), Firebase Auth, Tailwind/shadcn, Vitest + Playwright, Vercel
- Backend: FastAPI (`fastapi_backend/`, from vintasoftware/nextjs-fastapi-template), uv, SQLAlchemy 2 async,
  Alembic (platform + store trees), pytest, Vercel serverless
- Data and services: Neon Postgres (platform DB + one DB per store), Upstash Redis + QStash,
  Cloudflare R2, Resend, Sentry
- Payments: Stripe Billing (merchant subscriptions) and Stripe Connect direct charges (merchant is seller)

## Current phase
Foundation release (epics E1–E6, Jira KAN-4…KAN-9): restructure the monorepo, adapt the template backend,
and port the boilerplate's ~92 server actions to FastAPI. Multi-tenancy (E7–E9) follows. No live users or data.

## Key constraints
- The browser never calls FastAPI directly; only the Next.js server does
- The frontend holds no database credentials or server secrets once Foundation is complete
- Test-first, ≥80% coverage; ruff, mypy, ESLint and pre-commit must pass
- Store database migrations stay backward compatible and run from CI, never inside a request
- Work follows Jira (project KAN): To-do → In Progress → In Review → Done
- Plan of record: `.claude/plans/storecart-plan.md`

## Definition of done
- Foundation: every boilerplate feature works through FastAPI, the existing e2e suite passes,
  and the frontend has no DATABASE_URL or server secrets
- Per story: its Jira acceptance criteria are met, CI is green, and it has been reviewed and merged
