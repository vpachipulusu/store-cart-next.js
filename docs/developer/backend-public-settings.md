# Public platform settings (KAN-205)

`GET /v1/settings/currency` returns the platform currency code. The pricing and admin
subscriptions pages need it (today `getCurrencySymbol` reads Prisma); the frontend switch is a
separate follow-up. No Alembic revision, no model change.

## Contract

| | |
|---|---|
| Auth | `X-Internal-Key` only (decision D14: the browser never calls FastAPI). No user session. |
| Rate limit | `PUBLIC_SETTINGS_POLICY`: 120 requests per 60 s per client IP (`X-Client-IP`). Fails open; 429 with `Retry-After`. |
| 200 | `{"success": true, "data": {"currency": "USD"}}` |
| 304 | Empty body when `If-None-Match` matches the `ETag`. |
| Cache | `public, max-age=60, stale-while-revalidate=300` plus a content-hash `ETag`. 429 and 401 carry no cache header. |

## Value rules

The code is upper case, as the admin settings page stores it (`USD`, `EUR`, ...), so it maps
straight onto `CURRENCIES` in `nextjs-frontend/src/config/currencies.ts`. The stored value is
trimmed and upper-cased. A missing row, a non-string value, or a code outside the supported
list (`SUPPORTED_CURRENCIES` in `app/services/public_settings.py`, kept in step with
`currencies.ts`) answers the default `USD`, the same default `getCurrencySymbol` uses. A
database error is a 500 and is not cached.

The server trims and upper-cases the stored code, while the legacy frontend
(`fetchCurrencySymbol`) does an exact match on it. A stored `" eur"` therefore reads as `EUR`
here but falls back to `$` in the old Prisma path; the admin page only stores clean codes.

## Caching and consumers

- `Cache-Control` is `public`, so no shared cache or CDN may sit in front of FastAPI (it would
  replay the response to callers without `X-Internal-Key`). The value is non-sensitive, same
  stance as the storefront lookup.
- A currency change can take up to 60 s to show, plus up to 300 s of stale-while-revalidate.
- The Next.js wrapper that calls this route must stay behind `unstable_cache` (the existing
  1 h cache, tag `currency-setting`). The 120/min limiter is keyed by the client IP, which for
  server-side calls is the shared Next.js server IP, so uncached per-render calls could
  exhaust the bucket.

## Seeding

The `app_settings` table exists since baseline `0001`. The `currency` row is written by the
admin settings action and by `npm run db:seed:settings`. When it is absent the service default
applies, so no data migration or seed is needed for this endpoint.

## What is public

Only `currency` (`CurrencyData` in `app/api/v1/settings.py`). The repository selects the one
`value` column for the key `currency`, so no other setting can leave the database layer. To
expose another setting, add a route with its own schema; do not widen this one.

## Tests

- `tests/api/test_public_settings.py`: fake repository; set, unset, unknown and malformed values,
  allowlist, headers, ETag/304, rate limit, internal key.
- `tests/api/test_public_settings_e2e.py`: real Postgres (`TEST_DATABASE_URL`, see `testing.md`).
