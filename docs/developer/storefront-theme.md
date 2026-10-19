# Storefront theme pages (KAN-75)

A store host `{slug}.<root domain>` shows one theme: home, categories, products, search and a basket. The proxy rewrites the host to `src/app/storefront/[slug]/...` (see [storefront-subdomains.md](storefront-subdomains.md)); the cart routes are [backend-storefront-cart.md](backend-storefront-cart.md). Checkout is KAN-77.

## Pages

| Path on the store host | File | Cached |
|---|---|---|
| `/` | `[slug]/page.tsx` (welcome, top categories, 8 newest products) | yes |
| `/categories/{slug}` and `/categories/{slug}/page/{n}` | `[slug]/categories/...` (paging in the path, `/page/1` redirects) | yes |
| `/products/{slug}` | `[slug]/products/[productSlug]/page.tsx` (options, Add to basket, JSON-LD) | yes |
| `/search?q=&page=` | `[slug]/search/page.tsx` (no `q` lists everything) | no, `noindex` |
| `/basket` | `[slug]/basket/page.tsx` (shell cached; lines load in the browser) | shell only, `noindex` |

`/cart` is the cart API, so the basket page is `/basket`. Components live in `src/components/storefront/`; the header basket count and Add to basket call the store's own `/cart` routes from the browser (`src/lib/storefront/cart-client.ts`). The browser never calls FastAPI.

## Backend reads

`GET /v1/storefront/{slug}/products` (`category` slug, `q`, `limit` up to 100, `offset` up to 10 000), `/products/{product_slug}` and `/categories` (`app/api/v1/storefront_catalogue.py`, service `app/services/storefront_catalogue.py`). Internal key only, `no-store`, ACTIVE store only (same 404 as the lookup), published (`active`) products only; a draft reads like an unknown slug. Bodies have no SKU, weight, exact stock (`in_stock` only), product or category ids, or timestamps; variant and option value ids are there because the cart adds by variant. Search matches titles only (never SKUs). Image URLs are `R2_PUBLIC_BASE_URL/{key}`; without that setting products have no images. The platform currency comes with every product response. No Alembic revision.

Rate limit: `STOREFRONT_CATALOGUE_POLICY` (300/min). A request with a forwarded visitor IP is keyed by that IP; the Next.js server's shared cached reads (internal key, no IP) are keyed by store, so cache misses for one store never use up another store's budget.

## Caching and revalidation

Shared reads go through `src/lib/api/storefront-catalogue.ts`: `unstable_cache` per read, key `['storefront', read, slug, ...args]`, tag `storefront:{slug}` (`src/lib/storefront/cache.ts`), revalidate 300 s. They call `callBackend(..., { shared: true })`: no session, no visitor IP, no `no-store`, so the pages stay static (ISR with `generateStaticParams` returning `[]`). A 404 is cached as "not found"; any other failure throws, is never cached, and shows the storefront error page. Product and category slugs are checked (`isValidCatalogueSlug`) before any cached read, so a made-up URL costs no backend call.

- Merchant product changes (`src/app/actions/product-actions.ts`) call `revalidateTag('storefront:{slug}', { expire: 0 })`, so that store's pages refresh on the next visit and no other store's do.
- Everything else (store suspension, order-driven stock changes) shows within 300 s. The cart re-checks price and stock on every call.

## SEO

`src/lib/storefront/seo.ts`: the layout sets the store's `metadataBase`, title template `%s | {store}`, Open Graph site name, and clears the platform keywords, authors and manifest. Each page sets its canonical URL on the store host (`https://{slug}.{root}`, `http://{slug}.localhost:{PORT}` in development), Open Graph and Twitter cards. Products add schema.org `Product` JSON-LD (escaped so merchant text cannot close the script). Search and basket are `noindex`.

## Security notes

- The cached pages cannot read request headers, so the proxy keeps them off the platform origin: any direct `/storefront...` or `/storefront-preview...` request (after decoding and lower-casing) is rewritten to the internal 404, and the matcher always includes those paths.
- The `/s/{slug}` preview now targets `src/app/storefront-preview/[slug]/route.ts` (name only, CSP `default-src 'none'`), never the theme.
- Store hosts get `object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`.
- The search page is dynamic and can answer 200 (with `noindex`) for a missing store because the root `loading.tsx` streams; the cached pages answer 404.

## Tests

Backend: `tests/services/test_storefront_catalogue.py`, `tests/api/test_storefront_catalogue.py`, `tests/api/test_storefront_catalogue_e2e.py` (real Postgres). Frontend: `src/__tests__/unit/storefront/*`, `unit/api/storefront-catalogue.test.ts`, `unit/components/storefront.test.tsx`, proxy tests. E2E: `src/__tests__/e2e/storefront-theme.spec.ts` (seeds with `helpers/seed_storefront.py`; needs `E2E_BACKEND_DIR` like the cart spec).
