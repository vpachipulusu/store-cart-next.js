# Backend profile and account endpoints

KAN-38 exposes authenticated platform-user operations under `/v1/me`. The Next.js
server must supply `X-Internal-Key` and `X-Session-Token` as described in
[backend-auth.md](backend-auth.md). Firebase verifies session revocation and email
verification. The backend derives the platform user from the verified Firebase UID;
requests cannot choose another user's ID. Successful responses use `Cache-Control: no-store`.

| Method | Path                   | Result                                                                               |
| ------ | ---------------------- | ------------------------------------------------------------------------------------ |
| GET    | `/v1/me`               | Safe profile fields, excluding authentication secrets and billing                    |
| PATCH  | `/v1/me`               | Update display name, bio, location, website and phone number                         |
| PATCH  | `/v1/me/avatar`        | Store an HTTPS avatar URL, or null to clear it                                       |
| GET    | `/v1/me/settings`      | Settings, with system/true/en/UTC defaults when no row exists                        |
| PATCH  | `/v1/me/settings`      | Update supplied settings; preserve omitted fields                                    |
| GET    | `/v1/me/login-history` | Current-user history and total count; limit 10 by default, 1–100; offset nonnegative |
| DELETE | `/v1/me`               | Delete the Firebase and platform account after recent reauthentication               |

PATCH rejects unknown fields and empty bodies. Explicit null clears optional profile
fields; an empty website also clears it. Settings cannot be null. Avatar URLs are
metadata: the backend neither uploads nor fetches the URL. Responses never expose
two-factor secrets. Ordinary endpoints use the per-user API rate-limit policy;
deletion uses the fail-closed authentication policy.

## Account deletion

DELETE requires a JSON `id_token` from Firebase reauthentication within five minutes,
with the same UID as the verified session and a verified email. Stale, future, foreign
or unverified tokens fail. Any OWNER membership returns 409: transfer or remove
organization ownership first. Organization billing, subscriptions and stores remain
intact; personal rows and non-owner memberships use existing database cascades.

The service locks the user and membership rows, checks ownership, deletes Firebase,
then deletes and commits the platform user. Firebase failure leaves the database
intact. **These two systems cannot commit atomically:** if SQL deletion or commit fails
after Firebase succeeds, the endpoint returns failure and leaves a residual platform
row. Ordinary authenticated retries cannot proceed because the Firebase account is
gone. An operator must verify Firebase deletion, recheck organization ownership and
remove the residual platform user through a controlled repair procedure. Do not
recreate the Firebase identity automatically or claim successful deletion on SQL failure.
Future membership writers must follow the same user-row locking protocol.

## Validation and rollout

ASGI integration tests cover every endpoint, authentication/validation failures,
scope isolation and fail-closed deletion. Service tests cover reauthentication,
ownership, transaction rollback and cross-system failure ordering. Repository tests
inspect scoped SQL and row locks without a real database. No production database or
Firebase account is touched by tests.

Frontend action cutover remains KAN-41. Export remains KAN-114; password, TOTP,
notifications and billing changes are outside this ticket.
