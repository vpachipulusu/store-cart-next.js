# ADR-006: Docker for local development and CI only

- **Status:** Proposed
- **Date:** 2026-10-11
- **Plan decisions:** D20 (Docker Compose for local development)
- **Jira:** KAN-29; carried out in KAN-26 and KAN-30

## Context

The template ships a `Dockerfile` and a `docker-compose.yml` (database, test database, Redis, backend,
frontend). Production runs on Vercel serverless functions ([ADR-002](0002-hosting-on-vercel.md)), which do
not run our container images. Without a written rule, people could start treating the image as a deployment
artefact, or production behaviour could quietly drift from local.

## Decision

- Docker is for **local development and CI only**. No Docker image is deployed to production or previews.
- `docker-compose.yml` (adapted from the template) gives a one-command local stack: Postgres for the platform
  and at least two store databases, a test database, Redis, the backend and the frontend.
- CI can use the same images or service containers to run backend tests against real Postgres.
- The `Dockerfile` is still hardened (pinned uv base image, non-root user, no `curl | sh`), because CI runs it
  and developers run it with real credentials.
- Local service substitutes are documented next to the production services: Postgres for Neon, Redis with an
  HTTP shim (or Upstash dev) for Upstash, and a local or mocked QStash.

## Alternatives considered

- **No Docker; developers install Postgres and Redis locally.** Works, but setup differs per machine, and
  several store databases are tedious to create by hand.
- **Deploy the container to a container host.** Rejected by ADR-002 for now; it stays the fallback if KAN-115
  fails, in which case this ADR is revisited.

## Consequences

- One local setup for everyone, close enough to production to test multi-database routing.
- Container-only behaviour (for example a long-running process or local disk) must never be relied on.
  Serverless limits apply even when running locally in Docker.
