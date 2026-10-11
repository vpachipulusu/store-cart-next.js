# ADR-002: Hosting — two Vercel projects and serverless services

- **Status:** Proposed
- **Date:** 2026-10-11
- **Plan decisions:** D10 (frontend hosting), D13 (backend hosting), D18 (background jobs), D19 (file storage)
- **Jira:** KAN-29; carried out in KAN-28 and KAN-112

## Context

The team is small and has no operations capacity. The frontend already runs on Vercel. The template ships a
Vercel entry point for FastAPI. Every service in the stack (Neon, Upstash, R2, Resend, Sentry) is serverless or
reached over HTTP, so nothing needs a long-running server.

## Decision

- **Frontend (D10):** Vercel project rooted at `nextjs-frontend/`.
- **Backend (D13):** a second Vercel project rooted at `fastapi_backend/`, running FastAPI as Python serverless
  functions through the template's `api/index.py` and `vercel.json`.
- **Region:** both projects' functions run in the same region as the Neon databases, to keep database round
  trips short.
- **Background jobs (D18):** Upstash QStash calls signed backend endpoints. Each job step must finish inside
  one serverless invocation and be idempotent (for example store provisioning: create DB → migrate → mark ready,
  with a `failed` state after retries).
- **File storage (D19):** Cloudflare R2. The backend issues presigned upload URLs; files never pass through a
  function.
- **Environments:** preview deployments use a separate database from production and never run production
  migrations. Production deploys come only from the release workflow.
- **Migrations:** platform migrations run at deploy; store migrations run from a GitHub Actions job
  (`migrate_stores`), never inside a request (see [ADR-005](0005-per-store-database-access.md)).

## Alternatives considered

- **Container host for the backend (Fly.io, Render, Cloud Run).** Allows long-lived connection pools and
  long jobs, but adds a second platform to run and pay for. Kept as the fallback if the KAN-115 spike shows
  serverless cold starts plus per-store connections are too slow.
- **Celery/RQ workers (the template's Redis).** Needs an always-on worker; QStash gives retries and scheduling
  without one.
- **Vercel Blob or S3 for files.** R2 has no egress fees, which matters for storefront images.

## Consequences

- No servers to patch or scale; cost follows usage.
- Serverless limits shape the design: no in-process pools or caches, no in-memory rate limiting
  ([ADR-007](0007-rate-limit-keys.md)), every job split into short steps.
- Cold starts add latency to the first request on an instance. KAN-115 measures this, with a second store
  database, before E7 commits to the design.
- The backend has a public URL, so it must authenticate its caller
  ([ADR-003](0003-nextjs-to-fastapi-authentication.md)).
