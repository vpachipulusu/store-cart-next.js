# ADR-007: Rate limits keyed by user, organisation or store

- **Status:** Accepted by the product owner, 2026-10-12
- **Date:** 2026-10-11
- **Plan decisions:** none (new decision required by KAN-29)
- **Jira:** KAN-29; carried out in KAN-34

## Context

The boilerplate rate-limits by client IP in the Next.js proxy. Once the backend exists, every request it
receives comes from Vercel's servers ([ADR-003](0003-nextjs-to-fastapi-authentication.md)), so the IP it sees
says nothing about the end user. In-process counters do not work on serverless functions either. On top of
that, IP keys treat many shoppers behind one network as one client, and let one attacker spread requests across
many IPs.

## Decision

- **Authenticated requests are limited by who is acting:** the merchant user, and where relevant also by
  organisation and by store (for example the store's API and webhook volume). Keys look like
  `rl:{scope}:{user|org|store}:{id}`.
- **Unauthenticated auth endpoints** (sign-in, sign-up, password reset) are limited by the end-user IP that
  Next.js forwards, trusted only on requests that carry a valid service key, combined with the target account
  (for example email) where one exists.
- **Counters live in Upstash Redis** (HTTP), never in process memory.
- Going over a limit returns **429** with standard rate-limit headers, in the normal error envelope.
- The starting limits match the boilerplate's current auth, API and webhook settings. **What happens when Redis
  is unavailable** is decided and tested in KAN-34.
- The backend limits are the ones that count. The current in-memory limiter used by the Next.js proxy
  (`src/lib/middleware/rate-limit.ts`, a per-instance `Map`) gives no real protection on serverless. Any
  limit kept in the proxy must also use Upstash, or be removed.

## Alternatives considered

- **IP limits in the backend.** Meaningless behind the Next.js server (every request has a Vercel IP).
- **In-memory limits per function instance.** Reset on every cold start and differ per instance; no real
  protection.
- **Limits only in the Next.js proxy.** The backend has a public URL, so it must protect itself.

## Consequences

- Fair limits per merchant and per store, which can later follow the organisation's plan.
- Every limited request makes a Redis round trip; Upstash's HTTP latency is part of the request budget.
- Trusting the forwarded IP depends on the service key staying secret.
