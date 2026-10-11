# ADR-003: Authentication from the Next.js server to FastAPI

- **Status:** Proposed
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
     environments of both Vercel projects. FastAPI compares it in constant time and rejects requests without
     it before any other work. It proves the caller is our Next.js server. Two valid keys (current and next)
     are accepted so the key can be rotated without downtime.
   - **Forwarded Firebase session cookie:** the value of the `session` cookie, forwarded in a dedicated header
     (not as a browser cookie). FastAPI verifies it with the Firebase Admin SDK, including the revocation check,
     and turns it into the current merchant. This proves *who* the request is for.
4. **Signing in:** Next.js posts the Firebase ID token to `POST /v1/auth/session`. FastAPI verifies it, syncs
   the user, records login history and returns the session cookie value. Next.js sets the cookie in the
   browser. The Firebase Admin credentials then live only in the backend.
5. **Endpoints not called by Next.js** (Stripe webhooks, QStash callbacks) do not use the service key; each
   verifies its provider's signature instead.
6. **The client IP** for unauthenticated endpoints is forwarded by Next.js in a header, and is trusted only on
   requests that carry a valid service key ([ADR-007](0007-rate-limit-keys.md)).
7. **Authorisation** (organisation membership and role, store access) happens in the backend, in dependencies
   that run before any store database is opened ([ADR-005](0005-per-store-database-access.md)).

## Alternatives considered

- **Session cookie only, no service key.** Anyone holding a stolen session cookie could call the backend
  directly, skipping the Next.js layer's checks and rate limits.
- **Next.js mints short-lived JWTs for the backend.** Adds signing keys and a second token format; Firebase
  already gives a verifiable, revocable session.
- **Vercel Deployment Protection / private networking.** Not available for function-to-function calls on all
  plans and ties security to one host. Can be added on top later.
- **Browser calls FastAPI directly with an ID token.** Exposes the backend to the internet as a public API
  and puts CORS and token refresh in the browser, which goes against D14.

## Consequences

- A leaked session cookie alone cannot reach the backend; an attacker would also need a server secret.
- The service key is a high-value secret: it lives only in server env vars (never `NEXT_PUBLIC_*`), it is
  rotated by the two-key scheme, and it is never logged.
- The Firebase Admin SDK, and its private key, move from the frontend to the backend as part of E3/E6.
- Every backend call from Next.js goes through one server-only wrapper that attaches both headers.
