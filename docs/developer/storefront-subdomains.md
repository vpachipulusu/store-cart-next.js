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
