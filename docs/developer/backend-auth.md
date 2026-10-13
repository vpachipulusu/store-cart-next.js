# Backend Firebase sessions (KAN-37)

Only the Next.js server calls these endpoints, under [ADR-003](../adr/0003-nextjs-to-fastapi-authentication.md). The frontend continues using its current Firebase/Prisma authentication until KAN-41; this story adds the backend contract and credential forwarding, not the frontend switch.

| Endpoint                  | Behavior                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /v1/auth/session`   | Accepts `{ "id_token": "..." }`, verifies the ID token with revocation checks and authentication within five minutes, rate limits IP then verified email, mints a five-day session cookie, transactionally upserts the platform user by Firebase UID and records login history. Returns `{ success: true, data: { session_cookie, expires_in } }` only after commit. |
| `GET /v1/auth/session`    | Requires `X-Session-Token`, verifies the session with `check_revoked=True`, enforces the verified `email_verified` claim, and returns UID/email/verification status. This is the reusable authenticated dependency for later API routes.                                                                                                                             |
| `DELETE /v1/auth/session` | Verifies `X-Session-Token` and revokes the UID's refresh tokens. Firebase revocation affects all the user's sessions, not one cookie. Unverified users may sign out.                                                                                                                                                                                                 |

Each route requires `X-Internal-Key` before Firebase, database access or rate limiting. Current and next keys are compared in constant time to allow rotation. Health and provider-signed webhooks retain their existing boundaries; browser cookies, arbitrary forwarded headers, or a session token alone do not establish the internal caller.

The Next.js server-only wrapper sends `BACKEND_INTERNAL_KEY` and the current browser session value. It forwards `X-Client-IP` only from a validated Vercel `x-vercel-forwarded-for`, alongside the internal key. The backend trusts that header only after key validation, otherwise using the direct peer. Email limit identifiers use HMAC-SHA256 with a separate secret; raw emails never enter Redis keys. Auth limits fail closed with 503 and Retry-After; authenticated API limits retain their fail-open policy.

## Configuration before deployment

Configure these through secure environment settings; never paste values in logs, Jira or committed files. Use independent secrets per production/preview/development environment and distinct values for the service and HMAC keys. Existing Upstash production requirements still apply.

| Variable                      | Location / purpose                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------------- |
| `BACKEND_INTERNAL_KEY`        | Next.js server and backend; random secret of at least 32 characters.               |
| `BACKEND_INTERNAL_KEY_NEXT`   | Backend only; optional next secret of at least 32 characters during rotation.      |
| `RATE_LIMIT_EMAIL_KEY`        | Backend only; independent random secret of at least 32 characters for email HMAC.  |
| `FIREBASE_ADMIN_PROJECT_ID`   | Backend Firebase project ID, matching the environment's frontend identity project. |
| `FIREBASE_ADMIN_CLIENT_EMAIL` | Backend Firebase service-account email.                                            |
| `FIREBASE_ADMIN_PRIVATE_KEY`  | Backend service-account private key; escaped newlines are supported.               |

Production refuses to start when authentication configuration is missing. Local/test and Vercel preview/development can start without it, but auth endpoints fail closed when necessary configuration is absent. Firebase initialization is lazy, and all blocking SDK calls run off the asyncio event loop. Test/preview credentials must use the dedicated test project. The owner must configure production secrets and Upstash before a release; this implementation neither accesses production Neon nor creates cloud resources.

To rotate service keys: first add a new backend `BACKEND_INTERNAL_KEY_NEXT`; then deploy the frontend with that value as its current `BACKEND_INTERNAL_KEY`; then promote it to the backend's current key and remove the old next value. Keep the HMAC key stable unless deliberately resetting email limit buckets.

Next.js sets the returned session value as a Secure, HttpOnly, SameSite browser cookie and performs CSRF checks when the frontend moves to these endpoints in KAN-41. The backend returns a cookie value to its trusted server caller, not a browser Set-Cookie header. Responses use `Cache-Control: no-store`. Tokens, headers and private keys are not logged; normal 401/403/409/503 error envelopes contain no provider or database details.

Alembic owns the platform models and schema. The UID upsert avoids concurrent duplicate users; email conflicts reject the login and roll back user/history together, without linking accounts by email. Existing profile fields are preserved. No migration or production database operation is part of KAN-37. The carried unique `lower(email)` index and frontend limiter removal remain separate follow-ups.

## Verification

Backend tests use injected Firebase/repository/session/limiter fakes and never call real Firebase, Redis or a database. SDK adapter tests assert worker-thread execution and revocation flags. Repository tests inspect UID-based PostgreSQL upsert behavior. API tests cover service-key ordering/rotation, stale auth, session rejection, email verification, revocation, limiter outages, HMAC identities and rollback. Regenerate OpenAPI and the TypeScript client after endpoint changes, and run the existing coverage ratchet without lowering it.
