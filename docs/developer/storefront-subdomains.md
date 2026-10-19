# Storefront subdomain routing (KAN-64)

`{slug}.<root domain>` shows a store's public storefront. The proxy (`src/proxy.ts`) rewrites every path on a store host under the internal `src/app/storefront/[slug]/`, where the theme pages (KAN-75, [storefront-theme.md](storefront-theme.md)) look the store up through `GET /v1/storefront/{slug}` (KAN-65, see [backend-storefront-lookup.md](backend-storefront-lookup.md)). Unknown, suspended and any other non-live store gets a 404. A backend failure is an error page, never a 404. Direct `/storefront...` requests on the platform host are rewritten to the internal 404 by the proxy.

## Configuration

| Variable               | Where                | Notes                                                                                                                                                                                                                                                                               |
| ---------------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PLATFORM_ROOT_DOMAIN` | Next.js, server-only | Host name without scheme, path or port, for example `storecart.com`. Default `localhost`, which gives `{slug}.localhost:3000` in development. **Required in production**: if it is unset or invalid the proxy logs one warning and store subdomains fall through to the normal app. |

Production also needs wildcard DNS (`*.storecart.com`) and the wildcard domain added to the Vercel project. Keep the `session` cookie host-only (never `Domain=.storecart.com`) so it is never sent to store hosts.

Reserved names (`www`, `app`, `admin`, `api`, ...) are never stores. The list is a copy of `RESERVED_SLUGS` in `fastapi_backend/app/core/slugs.py`; a unit test fails if the two drift.

## Rate limiting and client IP

- Store hosts skip the proxy's edge rate limiting (the proxy rewrites before it runs). Each page view makes one backend lookup, so the only limit is the backend's `STOREFRONT_POLICY`: 120 requests per 60 s per client IP.
- `X-Client-IP` is forwarded only on Vercel (from `x-vercel-forwarded-for`, validated, `src/lib/api/server.ts`). On any other deployment no IP is sent, so all visitors share one backend bucket and a single client can exhaust it for every store. Deploy on Vercel, or add a trusted proxy that sets the IP, before relying on this off Vercel.
- The lookup is cached per store on the Next.js side (300 s, tag `storefront:{slug}`), and those cached reads send no visitor IP; see [storefront-theme.md](storefront-theme.md).

## Local development

Browsers resolve `*.localhost` to loopback, so open `http://acme.localhost:3000` with no hosts-file entry. The store must exist and be ACTIVE in the platform database. E2E: `src/__tests__/e2e/storefront-subdomain.spec.ts` (seeds described in its header).

## Preview-only path access: `/s/{slug}` (KAN-202, temporary)

`*.vercel.app` has no wildcard subdomains, so until a custom wildcard domain exists a store can be demoed at `/s/{slug}` on the platform URL. **Remove this route once the wildcard domain is live**: delete `parseStorePath`, `isStorefrontPathPreviewEnabled`, `STORE_PATH_PREFIX` and `STORE_NOT_FOUND_SLUG` from `src/lib/storefront/host.ts`, `rewritePathPreview` and its call in `src/proxy.ts`, `src/app/storefront-preview/` (and `STOREFRONT_PREVIEW_ROUTE`), their unit tests (the 200 body still carries a robots `index` meta; the `X-Robots-Tag: noindex` header wins, so no change is needed there), `src/__tests__/e2e/storefront-path-preview.spec.ts` and this section.

- **Gating (allow-list, fails closed):** served only when `STOREFRONT_PATH_PREVIEW` is exactly `true` AND (`VERCEL_ENV` is `preview` or `development`, OR `VERCEL_ENV` is unset and `NODE_ENV` is not `production`). Production, an unset `VERCEL_ENV` under a production build (self-hosted production, or Vercel system environment variables switched off), empty and unknown values all get the same 404. This is stricter than the story's "not production" on purpose. Local E2E uses a production build, so it needs `VERCEL_ENV=preview` too. Set the flag on the Vercel Preview environment only, never Production.
- **Custom environments:** Vercel custom environments report `VERCEL_ENV=preview`. A production-like custom environment (for example staging with real merchant data) must never get the flag.
- **Origin and content:** unlike a store subdomain, `/s/{slug}` is on the same origin as the dashboard and admin. It is preview-only for that reason. It must stay name-only and escaped (`renderDocument` escapes every value), must not render richer merchant content, and every `/s/*` response (200 and 404) carries `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'` so nothing on it can run script or load resources.
- **Same lookup, same 404:** the proxy validates the slug with the host-routing validator and reserved list and sets `x-storefront-slug` itself (any inbound copy is stripped on every request). Flag off, production, unknown, suspended, reserved and malformed slugs all return the host-routing 404 body, because the proxy rewrites them to the internal route without the marker. `X-Client-IP` is forwarded by the same `callBackend` path.
- **Not indexable:** every `/s/*` response carries `X-Robots-Tag: noindex`.
- Direct `/storefront/{slug}` requests still 404. A store host takes precedence over the `/s` path.
- E2E: `STOREFRONT_PATH_PREVIEW=true VERCEL_ENV=preview PLATFORM_ROOT_DOMAIN=localhost npm run test:e2e:local -- src/__tests__/e2e/storefront-path-preview.spec.ts` (same backend seed as `storefront-subdomain.spec.ts`).
