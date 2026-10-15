# Storefront subdomain routing (KAN-64)

`{slug}.<root domain>` shows a store's public storefront. The proxy (`src/proxy.ts`) rewrites every path on a store host to the internal route `src/app/storefront/[slug]/route.ts`, which looks the store up through `GET /v1/storefront/{slug}` (KAN-65, see [backend-storefront-lookup.md](backend-storefront-lookup.md)). Unknown, suspended and any other non-live store gets the same 404. A backend failure gives 503, never a 404.

## Configuration

| Variable               | Where                | Notes                                                                                                                                                                                                                                                                               |
| ---------------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PLATFORM_ROOT_DOMAIN` | Next.js, server-only | Host name without scheme, path or port, for example `storecart.com`. Default `localhost`, which gives `{slug}.localhost:3000` in development. **Required in production**: if it is unset or invalid the proxy logs one warning and store subdomains fall through to the normal app. |

Production also needs wildcard DNS (`*.storecart.com`) and the wildcard domain added to the Vercel project. Keep the `session` cookie host-only (never `Domain=.storecart.com`) so it is never sent to store hosts.

Reserved names (`www`, `app`, `admin`, `api`, ...) are never stores. The list is a copy of `RESERVED_SLUGS` in `fastapi_backend/app/core/slugs.py`; a unit test fails if the two drift.

## Rate limiting and client IP

- Store hosts skip the proxy's edge rate limiting (the proxy rewrites before it runs). Each page view makes one backend lookup, so the only limit is the backend's `STOREFRONT_POLICY`: 120 requests per 60 s per client IP.
- `X-Client-IP` is forwarded only on Vercel (from `x-vercel-forwarded-for`, validated, `src/lib/api/server.ts`). On any other deployment no IP is sent, so all visitors share one backend bucket and a single client can exhaust it for every store. Deploy on Vercel, or add a trusted proxy that sets the IP, before relying on this off Vercel.
- The lookup is not cached on the Next.js side.

## Local development

Browsers resolve `*.localhost` to loopback, so open `http://acme.localhost:3000` with no hosts-file entry. The store must exist and be ACTIVE in the platform database. E2E: `src/__tests__/e2e/storefront-subdomain.spec.ts` (seeds described in its header).

## Preview-only path access: `/s/{slug}` (KAN-202, temporary)

`*.vercel.app` has no wildcard subdomains, so until a custom wildcard domain exists a store can be demoed at `/s/{slug}` on the platform URL. **Remove this route once the wildcard domain is live**: delete `parseStorePath`, `isStorefrontPathPreviewEnabled`, `STORE_PATH_PREFIX` and `STORE_NOT_FOUND_SLUG` from `src/lib/storefront/host.ts`, `rewritePathPreview` and its call in `src/proxy.ts`, their unit tests (the 200 body still carries a robots `index` meta; the `X-Robots-Tag: noindex` header wins, so no change is needed there), `src/__tests__/e2e/storefront-path-preview.spec.ts` and this section.

- **Gating:** served only when `STOREFRONT_PATH_PREVIEW=true` and `VERCEL_ENV` is not `production`. `VERCEL_ENV` is unset off Vercel, so there the flag alone decides. Set the flag on the Vercel Preview environment only, never Production. **Never set `STOREFRONT_PATH_PREVIEW` on a non-Vercel production host: where `VERCEL_ENV` is unset the flag alone decides.**
- **Same lookup, same 404:** the proxy validates the slug with the host-routing validator and reserved list and sets `x-storefront-slug` itself (any inbound copy is stripped on every request). Flag off, production, unknown, suspended, reserved and malformed slugs all return the host-routing 404 body, because the proxy rewrites them to the internal route without the marker. `X-Client-IP` is forwarded by the same `callBackend` path.
- **Not indexable:** every `/s/*` response carries `X-Robots-Tag: noindex`.
- Direct `/storefront/{slug}` requests still 404. A store host takes precedence over the `/s` path.
- E2E: `STOREFRONT_PATH_PREVIEW=true npm run test:e2e:local -- src/__tests__/e2e/storefront-path-preview.spec.ts` (same backend seed as `storefront-subdomain.spec.ts`).
