# Public storefront lookup (KAN-65)

`GET /v1/storefront/{slug}` returns the public details of one store. KAN-64 (wildcard
subdomain routing) calls it from the Next.js server to decide whether `{slug}.<platform>` is a
live store. No Alembic revision, no model change.

## Contract

| | |
|---|---|
| Auth | `X-Internal-Key` only (decision D14: the browser never calls FastAPI). No user session. |
| Rate limit | `STOREFRONT_POLICY`: 120 requests per 60 s per client IP (`X-Client-IP`, trusted only after the internal key is validated). Fails open; 429 with `Retry-After` over the limit. |
| 200 | `{"success": true, "data": {"name": "...", "slug": "..."}}` |
| 304 | Empty body when `If-None-Match` matches the `ETag` (weak or strong form, a list, or `*`). |
| 404 | `{"success": false, "error": "Store not found"}` |

## What is public

Only `name` and `slug` (`StorefrontData` in `app/api/v1/storefront.py`). The repository selects
just those two columns, so `organization_id`, `database_ref`, `connection_string_encrypted`,
`status`, `schema_version` and timestamps never leave the database layer. To expose another
field, add it to `StorefrontData` and `PublicStore` deliberately; the tests fail on any extra field.

## Visibility

The query filters `status == ACTIVE`. It does not list statuses to exclude, so PROVISIONING,
SUSPENDED, ARCHIVED and any status added later (for example FAILED) are invisible by default.
Unknown, non-ACTIVE, malformed (not 3 to 63 chars of `a-z0-9-`, ASCII only, single hyphens) and
reserved slugs all return the same 404 with the same headers; malformed and reserved slugs do not
reach the database. Slugs are matched case-insensitively and returned in canonical lower case.

## Caching

| Response | `Cache-Control` |
|---|---|
| 200 / 304 | `public, max-age=60, stale-while-revalidate=300` plus `ETag` (SHA-256 of the body) |
| 404 | `public, max-age=30` |

A suspension is therefore visible within about a minute (up to 6 with stale-while-revalidate).
429 and 401 carry no cache header. Rate-limit headers are not sent on cacheable responses.

## Deployment assumptions

- **Only the Next.js server calls this and it is the only cache.** `Cache-Control: public` is safe
  because the body is identical for every caller. Do not put a CDN or shared cache in front of
  FastAPI for this route: it would replay responses to callers without `X-Internal-Key`. If one is
  ever added, switch to `private` or add `Vary: X-Internal-Key`.
- **The caller must forward `X-Client-IP`.** Without it the limit keys on the peer address, so every
  lookup from the Next.js server would share one 120/min bucket. KAN-64 must send the end-user IP.
- A store that becomes ACTIVE may still read as 404 for up to 30 s (the miss cache).

## Tests

- `tests/api/test_storefront.py`: fake repository; field allowlist, headers, ETag/304, slug
  validation, rate limit, internal key.
- `tests/api/test_storefront_e2e.py`: real Postgres (`TEST_DATABASE_URL`, see
  `docs/developer/testing.md`); every non-ACTIVE status is a 404 identical to an unknown slug,
  secret columns never appear in the body, tenants do not leak into each other.
