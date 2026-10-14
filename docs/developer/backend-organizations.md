# Backend: organisation and store APIs (KAN-59)

Authenticated routes in `fastapi_backend` to create, list and update organisations and stores. Every route needs
`X-Internal-Key`, a verified session (`X-Session-Token`, verified email) and is rate limited by subject
(`API_POLICY`). Responses use `{"success": true, "data": ...}` with `Cache-Control: no-store`; errors use the usual
`{"success": false, "error": "..."}` envelope. Code: `app/api/v1/organizations.py`, `app/api/v1/stores.py`,
`app/services/organizations.py`, `app/repositories/organizations.py`, `app/core/slugs.py`.

## Routes

| Method and path                      | Who                            | Purpose                                                                     |
| ------------------------------------ | ------------------------------ | --------------------------------------------------------------------------- |
| `GET /v1/organizations`              | any caller                     | **The caller's own organisations only**, each with their `role` and stores  |
| `POST /v1/organizations`             | any caller                     | Create an organisation; the caller becomes its `OWNER` (same transaction)   |
| `GET /v1/organizations/{id}`         | member                         | One organisation with role and stores                                       |
| `PATCH /v1/organizations/{id}`       | name: OWNER/ADMIN; slug: OWNER | Rename and/or change slug                                                   |
| `GET /v1/organizations/{id}/stores`  | member                         | Paginated stores                                                            |
| `POST /v1/organizations/{id}/stores` | OWNER/ADMIN                    | Create a store in `PROVISIONING` status                                     |
| `GET /v1/stores/{store_id}`          | member (`require_merchant`)    | One store                                                                   |
| `PATCH /v1/stores/{store_id}`        | name: OWNER/ADMIN; slug: OWNER | Rename and/or change slug of an `ACTIVE` store                              |

`GET /v1/organizations` is the lookup the frontend uses server-side (for example before the billing routes, which
take an `organization_id`). It reads only the `memberships` table for the verified caller, so it can never list
another user's organisations. `limit` is 1 to 100 (default 50), `offset` 0 to 100000; the response carries `total`.
Each organisation lists up to 100 non-archived stores (`stores_truncated` is true when there are more; use
`GET /v1/organizations/{id}/stores`). Subscription and Stripe fields are not returned here; billing stays
OWNER/ADMIN-only under `/billing`.

## Authorisation

- Organisation, owner and role are **never** read from a body: bodies accept only `name` and `slug` and reject
  unknown fields (422).
- A non-member gets 404 `Organization not found`, identical whether or not the organisation exists. A member whose
  role is too low gets 403 `Forbidden`. `STAFF` is read-only.
- Writes lock the organisation or store row (`FOR UPDATE`) and re-read the membership in the same transaction, so a
  revoked membership cannot be used and concurrent creates are serialised.
- Store routes by id use `require_merchant` (KAN-52). Because it treats every non-GET request as a write, `PATCH`
  works only on an `ACTIVE` store (403 `Store is not active` otherwise). Stores start `PROVISIONING`; the
  provisioning job (KAN-56) moves them to `ACTIVE`.
- Every create and update writes an `audit_logs` row (`org.create`, `org.update`, `store.create`, `store.update`;
  resource `organization` or `store`; before/after name and slug) in the same transaction as the change.

## Slugs

`app/core/slugs.py`: ASCII only (checked before lower-casing, so look-alikes such as the Kelvin sign cannot fold to
`k`), lower-cased, 3 to 63 characters of `a-z`, `0-9` and single hyphens, no leading or trailing hyphen (so no
`xn--`). Reserved words (`www`, `admin`, `api`, `app`, `mail`, `ftp`, `static`, `assets`, `cdn`, `dashboard`, `help`,
`support`, `blog`, `status` and more; see `RESERVED_SLUGS`) are 422 `Slug is reserved`; a bad format is 422.

Uniqueness is case-insensitive because slugs are stored lower-case, enforced by the existing unique constraints plus
migration `0003` (`CHECK (slug = lower(slug))` on `organizations` and `stores`). Creation uses
`INSERT ... ON CONFLICT (slug) DO NOTHING`, so concurrent requests for one slug end with one 201 and the rest 409
`Slug is already taken`; a slug update that loses a race also returns 409. Store slugs are unique across all
organisations. A slug freed by a change can be taken by someone else.

## Limits and errors

| Status | When                                                                                                                                                                                         |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 409    | Slug taken; the plan's store limit is reached (`max_stores` in `app/core/plans.py`, archived stores do not count); the caller already owns 10 organisations (abuse guard, `MAX_OWNED_ORGANIZATIONS`) |
| 422    | Bad or reserved slug, bad name (1 to 100 characters, no control or bidi characters), empty update, unknown body field, pagination out of range                                              |
| 403    | Role too low; slug change by a non-OWNER; store not `ACTIVE` on update                                                                                                                       |
| 404    | Not a member, or unknown organisation or store                                                                                                                                               |

The store-limit check runs under the organisation row lock, so parallel requests cannot overshoot the plan limit.

## Tests

`tests/core/test_slugs.py` (unit) and `tests/api/test_organizations_e2e.py` (real Postgres through the real routes,
including concurrency races). The e2e file runs when `TEST_DATABASE_URL` points at a local `*_test` database; see
[testing.md](testing.md).
