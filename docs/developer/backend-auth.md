# Backend Firebase sessions (KAN-37)

Only the Next.js server calls these endpoints, under [ADR-003](../adr/0003-nextjs-to-fastapi-authentication.md). The frontend continues using its current Firebase/Prisma authentication until KAN-41; this story adds the backend contract and credential forwarding, not the frontend switch.

| Endpoint                  | Behavior                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /v1/auth/session`   | Accepts `{ "id_token": "..." }`, verifies the ID token with revocation checks and authentication within five minutes, rate limits IP then verified email, mints a five-day session cookie, transactionally upserts the platform user by Firebase UID and records login history. Returns `{ success: true, data: { session_cookie, expires_in } }` only after commit. |
| `POST /v1/auth/session/refresh` | Accepts `{ "id_token": "..." }` and requires the current `X-Session-Token` (KAN-179). The session is verified with revocation checking but, unlike most routes, an unverified-email session is allowed, because refresh is how `email_verified` gets re-synced after the user verifies. The ID token must verify (with revocation) for the **same UID** as the session; a mismatch is a generic 401 before any cookie is minted, and a missing or invalid session is 401, so a bare ID token can never mint a session here. There is **no `auth_time` freshness check**, `sync_user` only (so `email_verified` and email follow the token; `last_login_at` is left alone because a refresh is not a sign-in) and **no login-history row** (KAN-163). Rate-limited per user (`AUTH_POLICY`, key `user:<uid>`, fails closed with 503). Returns the same `{ success, data: { session_cookie, expires_in } }` as sign-in, only after the sync commits; 409 on an email conflict. Firebase's own `createSessionCookie` may still reject an ID token it considers too old; that surfaces as a 401/503 and the caller should fetch a fresh token with `getIdToken(true)`. |
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

## Platform admin permissions and audit logging (KAN-46)

`require_admin("users.read", ...)` in `app/api/admin.py` is the dependency factory for every platform-admin route (KAN-47/48/49). It reuses the session dependency above, then reads the caller's `admin_users` row by verified Firebase UID. 401: no or invalid session; 403 (one generic `Forbidden` body): unverified email, no admin record, empty or malformed grant, or any required permission missing. Nothing in the request (header, query, body) is consulted. Declaring no, unknown or `*` permissions raises at import time; the known names are `ADMIN_PERMISSIONS` in `app/core/permissions.py`, and new endpoints append there.

**Wildcard decision.** The stored `*` is honoured only for role `super_admin`, where it expands to the known `ADMIN_PERMISSIONS`. On role `admin` it is ignored, and unknown strings are dropped. This keeps the legacy self-grant bug (KAN-124) from reappearing: the grant endpoints in KAN-47 must call `assert_can_grant(admin, role, permissions)` (`app/core/permissions.py`) before writing an admin record. It requires `admins.create`, lets only a `super_admin` grant `*` or the `super_admin` role, and refuses permissions the actor does not hold.

**Audit.** The existing `audit_logs` table is reused, so there is no migration. Admin routes take `AuditorDep` and call `auditor.record(admin, action="admin.users.update", resource="users", resource_id=<target id>, before=..., after=..., details=...)` on the same `SessionDep` session as the change, then commit once, after `record` (the helper only stages and flushes; the session never auto-commits). Never commit the change first. If `record` raises, the route exits before its commit, so the change rolls back. Each row holds the actor's user id, action (`area.verb`), resource and target id, optional organisation id, IP (`client_ip`), user agent, and `metadata` with `actor_role`, `request_id`, `before`, `after` and `details`. Values under secret-looking keys (password, token, session, cookie, TOTP and 2FA material, API and private keys) and raw PII (email, phone, address) are replaced with `[REDACTED]` (keys are NFKC-normalised, look-alike keys are redacted, and string values that look like credentials are redacted whatever their key; pass `model_dump()` output, not models, and log changed field names rather than PII values); unknown objects are stored as their type name, and depth, list length and string length are bounded. Denied requests write no audit row (they are logged without payload). `AuditRepository` exposes `add` only, so the application never updates or deletes rows; the table has no database-level immutability guard.

## Merchant (store) authorisation (KAN-52)

`require_merchant(roles, write=False)` in `app/api/merchant.py` is the dependency for every store-scoped route (`/v1/stores/{store_id}/...`; the path parameter must be named `store_id`). It sits on the existing chain (internal key, then verified session, so 401 or 403 for an unverified email come first), then calls `MerchantService.authorize`. It returns a frozen `MerchantAccess` with `user_id`, `organization`, `store` and `role`. `roles` defaults to every `MembershipRole`; use `OWNER_ADMIN` for management routes. Declaring an empty role set raises at import time. Routers still declare `require_internal_key` themselves, as the billing router does.

**Authorisation reads the database on every request.** One statement joins `users` (by verified Firebase UID), `memberships`, `organizations` and `stores`, so the role is the live `memberships.role`. Nothing in the token, header, query or body is consulted.

**No leak between "no such store" and "not your store".** An unknown store id, a store of another organisation, a caller with no membership in the owning organisation and a caller with no platform user row all produce no row from that single query and the same `404 {"success": false, "error": "Store not found"}`. There is no second lookup, so the same query and code path serve every case (response bodies are asserted byte-identical in the Postgres e2e test; timing is not measured). Malformed ids (empty, over 128 characters, NUL) get the same 404 without a lookup. Only a member of the owning organisation can see a 403: `Forbidden` for a role outside `roles`. A user with memberships in two organisations only reaches the stores of the organisation that matches the store.

**Store status policy.** The role check runs first, then status:

| Store status                | Reads (`write=False`) | Writes (`write=True`)     |
| --------------------------- | --------------------- | ------------------------- |
| `ACTIVE`                    | allowed               | allowed                   |
| `SUSPENDED`, `PROVISIONING` | allowed               | 403 `Store is not active` |
| `ARCHIVED`                  | 404 (treated as gone) | 404                       |

A suspended store stays readable so a merchant can still see and export their data and see why they are blocked; any mutation is refused. A store that is still provisioning has no usable database yet, so it is read-only too. Every route that changes store state should pass `write=True`; as a safety net any method other than GET, HEAD or OPTIONS is treated as a write even without the flag. Denials are logged with the store id only (no token, no email).

**Known limits.** The check and a later write are separate transactions, so a membership removed or a store suspended between them can still be written by that one in-flight request (same window as `OrgBillingService`); writes that need a hard guarantee must re-check inside their own transaction. Users and organisations have no disabled flag today; add any future one to the `find_access` query. Run `require_merchant` before anything stages writes on the request session, because `authorize` rolls it back.

**Transactions.** `authorize` ends its read transaction (rollback) before returning, so no connection stays held across later work, as in `OrgBillingService.authorize`.

**Tests.** `tests/api/test_merchant.py` covers every role, missing membership, suspended, provisioning and archived stores, ordering with 401/403, and ignoring request claims. `tests/api/test_merchant_e2e.py` runs the dependency through real routes on Postgres when `TEST_DATABASE_URL` points at a local `*_test` database:

```bash
docker run -d --name kan52-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=kan52_test -p 55432:5432 postgres:17
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/kan52_test uv run pytest tests/api/test_merchant_e2e.py
```

## Session refresh and `two_factor_enabled` (KAN-179)

`GET /v1/me` (and the profile PATCH responses) now include `two_factor_enabled`, read from `users.two_factor_enabled` (no migration). The security page uses it for 2FA status; the secret is never returned.

Known limits (security review): (1) a logout or revocation racing between session verification and minting can still yield one new cookie; the window is a single Firebase round trip. (2) Refresh upserts by UID like sign-in, so it recreates a missing row. (3) Neither sign-in nor refresh enforces the second factor here; that stays with the Next.js layer (KAN-125).

Tests: `tests/api/test_auth.py` covers refresh with fakes. `tests/api/test_auth_refresh_e2e.py` runs the real routes, auth service and repositories on Postgres (UID mismatch, no or invalid session, stale ID token accepted, `email_verified` synced, no `login_history` row, `two_factor_enabled` on `/v1/me`) against a throwaway local `*_test` database; only Firebase is replaced:

```bash
docker run -d --name kan179-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=kan179_test -p 55432:5432 postgres:17
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/kan179_test uv run pytest tests/api/test_auth_refresh_e2e.py
```
