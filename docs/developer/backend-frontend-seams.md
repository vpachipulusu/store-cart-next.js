# Endpoints that replace the frontend's stripe and firebase-admin calls (KAN-208, backend half)

The Next.js server still imports `stripe` and `firebase-admin` in a few places. These endpoints cover every
remaining use so a later frontend PR can delete both packages. This PR changes no frontend code except the
regenerated client. All routes are called only by the Next.js server (decision D14), so each needs
`X-Internal-Key`. No Alembic revision, no model change.

| Frontend call today | Backend route |
| --- | --- |
| `stripe.prices.retrieve` in `config/subscriptions.ts` (pricing and admin subscriptions pages) | `GET /v1/settings/plan-prices` (new) |
| `verifySessionCookie(cookie, true)` in `verified-session.ts`, `pricing/page.tsx`, `hasMatchingActiveSession` | `GET /v1/auth/session/status` (new); `GET /v1/auth/session` still exists for "verified email required" |
| `verifyIdToken(idToken, true)` in `establishSession` | `POST /v1/auth/id-token/verify` (new) |
| `verifySessionCookie(.., false)` + `revokeRefreshTokens` on sign-out | `DELETE /v1/auth/session` (already exists, KAN-37; nothing added) |
| `getAdminAuth().updateUser(uid, { password })` in `changePasswordAction` | `PUT /v1/me/password` (new) |

There is no Firebase *profile* sync in the frontend: the only `updateUser` call is the password change, so
`PATCH /v1/me` is unchanged. `scripts/e2e-accounts.mjs` (a test helper that creates Firebase users) is not
covered; the frontend PR decides whether it keeps `firebase-admin` as a dev-only dependency.

## `GET /v1/settings/plan-prices`

Auth: internal key only, no session. Rate limit: `PUBLIC_SETTINGS_POLICY` per client IP (fails open, 429 with
`Retry-After`), like the currency route. Reads the four `STRIPE_PRICE_ID_{PRO,ENTERPRISE}_{MONTHLY,YEARLY}`
settings and asks Stripe for each price's `unit_amount`.

```json
{ "success": true, "data": { "pro": { "monthly": 1900, "yearly": 19000 }, "enterprise": { "monthly": null, "yearly": null } } }
```

Amounts are **minor units** (cents); the frontend divides by 100 as it does today. A price that is not
configured, not readable, or has no `unit_amount` is `null`, and one failing price never hides the others, so
the frontend needs a per-price fallback: today `fetchStripePrices` maps a missing amount to 0 and falls back to
`FALLBACK_PRICES` only as a whole. A missing `STRIPE_SECRET_KEY` gives
all `null` (200), not 503. `Cache-Control: private, max-age=300`; the frontend keeps its own one-hour cache,
which also keeps Stripe traffic low (there is no server-side cache; each uncached call makes four Stripe
reads, so the Next.js cache must stay in place). Use a restricted Stripe key where possible. Price ids are validated against
`price_[A-Za-z0-9]+` before they reach the Stripe path. No Stripe text reaches a log or a response.

## `GET /v1/auth/session/status`

Needs `X-Session-Token`. Verifies the session cookie with revocation checking and returns
`{ uid, email, email_verified }`. Unlike `GET /v1/auth/session` it **allows an unverified email** (callers read
`email_verified` and decide; the frontend's `EmailNotVerifiedError` check stays a one-liner) and uses the
per-user `API_POLICY` (100/min, fails open) instead of `AUTH_POLICY` (5 per 15 minutes, fails closed), so a
server can call it on every request. 401 for a missing, invalid or revoked session, 503 when Firebase is
unreachable. `Cache-Control: no-store`.

## `POST /v1/auth/id-token/verify`

Body `{ "id_token": "..." }` (1 to 16384 characters, never logged). Verifies signature, expiry and revocation
and returns `{ uid, email, email_verified }`. It writes nothing and applies no `auth_time` freshness check:
sign-in (`POST /session`, five minutes) and refresh (`POST /session/refresh`, same UID) keep their own rules.
It proves identity only, never a recent sign-in (a stolen ID token verifies for up to an hour), so anything sensitive must use a re-authentication check such as `PUT /v1/me/password`'s. Rate limit: `API_POLICY` per client IP (fail-open, keyed on the forwarded `X-Client-IP`), not `AUTH_POLICY`, so a sign-in that calls verify and then create does
not spend two of the five auth attempts. 401 for an invalid or revoked token, 503 for a Firebase outage.

## `PUT /v1/me/password`

Needs a verified session and the internal key. Body `{ "id_token": "...", "new_password": "..." }`
(`new_password` 8 to 128 characters, unknown fields rejected, both secrets never logged or echoed). The
`id_token` is a fresh Firebase ID token the browser minted by re-authenticating with the **current password**
(the same pattern as account deletion, KAN-180): it must belong to the session's UID, have a verified email,
an `auth_time` within five minutes and `firebase.sign_in_provider == "password"` (so a recent Google sign-in
cannot add a password credential), otherwise 401 before any change. A password Firebase refuses is 422
"Password does not meet requirements" (no Firebase text). The backend then sets the new password with
the Admin SDK (off the event loop). `AUTH_POLICY` per user (fails closed, 503). Responses: 200 `{ "success":
true }`, 401, 404 (no platform user row, or the Firebase user vanished), 422 (password rejected), 503, all
`no-store`. Failed attempts spend the same five-per-15-minutes budget, so the frontend should show a sensible 429.

The frontend currently checks the current password itself against the Identity Toolkit REST endpoint and
then calls Admin `updateUser`. The frontend PR should switch `changePasswordAction` to the re-authentication
flow `deleteAccountAction` already uses (browser re-auths, server forwards the ID token) and drop the REST check.
Firebase documents that a password change revokes the user's refresh tokens, so other sessions stop passing
the revocation check, **including the caller's own session cookie**: after a 200 the frontend must sign the user
in again with the **new password** to get a new ID token, then call `POST /v1/auth/session`; the re-auth ID token
predates the revoke, so `check_revoked` would likely reject it (401). Otherwise the user is signed out on the next call. This
endpoint adds no revocation of its own, and the behaviour (including this re-sign-in sequence) is unverified against live Firebase; the frontend PR's test plan must cover it. Google-only accounts therefore cannot use this
endpoint; the current frontend check already fails for them too.

## Tests

`tests/api/test_plan_prices.py`, `tests/services/test_plan_prices.py`, `tests/core/test_stripe_prices.py`,
`tests/api/test_auth_status.py`, and the password cases in `tests/api/test_me.py`, `tests/services/test_me.py`
and `tests/core/test_firebase.py`. All use fakes; no network, Stripe, Firebase or database.
