# ADR-003: Authentication from the Next.js server to FastAPI

- **Status:** Accepted by the product owner, 2026-10-12
- **Date:** 2026-10-11
- **Plan decisions:** D14 (frontend → backend), D21 (merchant auth)
- **Jira:** KAN-29; carried out in KAN-30 and E3 (KAN-36 …)

## Context

Merchants sign in with Firebase today. The Next.js server verifies the ID token and sets an httpOnly
`session` cookie holding a Firebase session cookie. The backend runs on its own public Vercel URL
([ADR-002](0002-hosting-on-vercel.md)), so any request reaching it must prove two things: that it came from
our Next.js server, and which merchant it acts for.

## Decision

1. **Only the Next.js server calls FastAPI (D14).** Server components, server actions and route handlers call it
   through the generated client ([ADR-008](0008-api-client-generation.md)); the browser never does. The
   backend therefore allows no browser origins in CORS.
2. **Firebase stays the merchant identity provider (D21).** The template's fastapi-users and JWT secrets are
   removed.
3. **Each backend request carries two credentials:**
   - **Internal service key:** a shared secret in an `X-Internal-Key` header, held only in the server
     environments of both Vercel projects (the Next.js server reads it from `BACKEND_INTERNAL_KEY`, never a
     `NEXT_PUBLIC_*` variable). FastAPI compares it in constant time and rejects requests without
     it before any other work. It proves the caller is our Next.js server. Two valid keys (current and next)
     are accepted so the key can be rotated without downtime. **Each environment has its own keys**
     (production, preview, development), so a preview frontend cannot call the production backend.
   - **Forwarded Firebase session cookie:** the value of the `session` cookie, forwarded in an
     `X-Session-Token` header (not as a browser cookie). FastAPI verifies it with the Firebase Admin SDK,
     including the revocation check, and turns it into the current merchant. This proves *who* the request is
     for. The revocation check costs a Firebase round trip per request; KAN-115 includes it in its latency
     numbers.
   - Both headers are redacted from request logs and Sentry events.
4. **Signing in:** Next.js posts the Firebase ID token to `POST /v1/auth/session`. FastAPI verifies it, rejects
   tokens whose `auth_time` is older than 5 minutes (Firebase's guidance for minting session cookies), syncs the
   user, records login history and returns the session cookie value. Next.js sets the cookie in the browser.
   The Firebase Admin credentials then live only in the backend.
5. **Endpoints not called by Next.js** (Stripe webhooks, QStash callbacks) do not use the service key; each
   verifies its provider's signature instead. `/health` (liveness, no database) is also public and returns no internal detail; `/health/ready` queries the
   database, so it requires the service key (KAN-247). Because
   the backend URL is public, the OpenAPI document and docs UI are switched off in production.
6. **The client IP** for unauthenticated endpoints is forwarded by Next.js in an `X-Client-IP` header, and is
   trusted only on requests that carry a valid service key ([ADR-007](0007-rate-limit-keys.md)). Next.js takes
   it from the header set by the platform (Vercel's `x-vercel-forwarded-for`, or `x-real-ip`), never from the first client-supplied `X-Forwarded-For`
   entry. FastAPI ignores inbound `X-Forwarded-For`.
7. **Authorisation** happens in the backend, in dependencies that run before any store database is opened
   ([ADR-005](0005-per-store-database-access.md)): organisation membership and role, store access, and the
   platform-admin role for E5's admin endpoints. Email verification is enforced here from the verified token
   claims (`email_verified`), not from a cookie the browser can set.

## Alternatives considered

- **Session cookie only, no service key.** Anyone holding a stolen session cookie could call the backend
  directly, skipping the Next.js layer's checks and rate limits.
- **Next.js mints short-lived JWTs for the backend.** Adds signing keys and a second token format; Firebase
  already gives a verifiable, revocable session.
- **Vercel Deployment Protection / private networking.** Not available for function-to-function calls on all
  plans and ties security to one host. Can be added on top later.
- **OAuth 2.0 (client credentials or an authorization server) between Next.js and FastAPI.** Rejected (KAN-247):
  there is one caller, the Next.js server, so a shared rotatable service key plus the revocable Firebase session
  gives the same assurance without a token issuer, scopes or a second token lifecycle. Revisit only if a second
  machine caller appears.
- **Browser calls FastAPI directly with an ID token.** Exposes the backend to the internet as a public API
  and puts CORS and token refresh in the browser, which goes against D14.

## Consequences

- A leaked session cookie alone cannot reach the backend; an attacker would also need a server secret.
- The service key is a high-value secret: it lives only in server env vars (never `NEXT_PUBLIC_*`), it is
  rotated by the two-key scheme, and it is never logged.
- The Firebase Admin SDK, and its private key, move from the frontend to the backend as part of E3/E6.
- Every backend call from Next.js goes through one server-only wrapper that attaches both headers.
