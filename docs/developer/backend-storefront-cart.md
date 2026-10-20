# Server-side cart (KAN-76)

Shoppers keep a cart per store. Only the Next.js server calls the backend (D14); the browser calls the storefront host.

## Flow

Browser → `{slug}.<root>/cart[/items[/{variantId}]]` (Next.js route handlers under `src/app/storefront/[slug]/cart/`, store hosts only) → `src/lib/api/cart.ts` → `/v1/storefront/{slug}/cart` (FastAPI).

| Route | Effect |
|---|---|
| `GET /cart` | The cart, priced now. No cart reads as empty and creates nothing. |
| `POST /cart/items` `{variant_id, quantity}` | Adds to the quantity in the cart; starts a cart when there is none. |
| `PUT /cart/items/{variant_id}` `{quantity}` | Sets the quantity; adds the line when it is not in the cart yet. |
| `DELETE /cart/items/{variant_id}` | Removes the line. |

## Store-scoped cookie

The cart token (32 random bytes, 43 url-safe chars) lives in an httpOnly, SameSite=Lax cookie named `sc_cart_<slug>` (`__Host-sc_cart_<slug>` in production, which also blocks cookie tossing from sibling subdomains). It is host-only on a store subdomain and lives 30 days; every successful write re-sets it (same token, fresh max-age), so it slides with the backend's `expires_at`. The backend stores only its SHA-256 (`carts.token_hash`) and returns the token once, in `cart_token`, when a write starts a cart; `src/lib/api/cart.ts` sets the cookie and never passes the token on. SameSite=Lax does not separate sibling store subdomains (same site); the route handlers refuse writes whose `Origin` is another host, which is what stops another store's page from writing to this cart. Each store has its own database, so a token or variant id from one store is nothing in another.

## Prices and stock are re-checked every time

`cart_items` holds only `variant_id` and `quantity`. Every response re-reads name, price, stock and product status from the catalogue and recomputes totals with `compute_totals` (store shipping and tax settings). A line is `ok`, or `unavailable` (product no longer active), `out_of_stock` or `limited` (quantity above stock); only `ok` lines count in the totals and `can_checkout` needs every line `ok`. Writes refuse a variant that is not sellable or does not exist (404 "That item is not available") and a quantity above stock (409 "Only N in stock"). Variant ids must match `^[A-Za-z0-9_-]{1,100}$` on both sides. Stock is not reserved. The client can name only a variant and a quantity (1 to 99, at most 50 lines).

## Notes

- Migration: store `0007_carts` (expand-only). Carts expire 30 days after the last write. Creating a cart also removes up to 20 expired ones (`EXPIRED_PURGE_LIMIT`); the scheduled purge below does the rest.
- Per-client limit: `CART_POLICY`, 60/min per client IP, fails open.
- `/s/{slug}` path preview does not serve cart routes (store hosts only).
- Known limit: two first adds sent at once by a shopper with no cart (a double click) create two carts; the cookie keeps the last token, so one line can be lost. Rare, and the shopper sees the cart they have.
- Tests: see the end of this page.

## Abuse limits (KAN-252)

Creating a cart needs no account and the row lives 30 days, so three limits keep one client from filling a store's database.

**1. Per-store creation cap.** `CART_CREATE_POLICY` (`app/core/rate_limit.py`): `CART_CREATE_PER_STORE_PER_HOUR = 600` new carts per store per hour, counter `rl:cart_create:store:{store_id}` (keyed by the store id resolved from the slug, never by client input). It is checked in `StoreCartService._write` by the `CartCreationGuard` (`app/services/store_cart_limits.py`), only when a request is about to start a cart and only after the request was validated (quantity, variant, stock), so a request that would fail with 404 or 409 does not spend the cap. Over the cap: **429** `Too many requests` with `Retry-After`, no cart row, no token. A request that carries a live cart token never reaches the cap: shoppers with a cart keep adding, changing, removing and reading. The cap counter is spent before the write is committed, so a write that then fails (for example the variant is deleted in between) burns one slot. Known limit (accepted trade-off): one client can use the whole cap (60 writes/min per client reaches 600 in about 10 minutes), after which new shoppers of that store get 429 until the hour slides; existing carts keep working. This turns a storage attack into a no-new-carts attack on one store, which is the accepted trade-off. The cap is shared by all clients of the store (and by `PUT /items/{id}` without a cart), on top of `CART_POLICY`.

**2. IPv6 keys group by /64.** `client_bucket` (`app/core/rate_limit.py`) turns the client address into the key part: IPv4 is unchanged, IPv6 becomes its `/64` (`2001:db8:1:2::/64`), an IPv4-mapped IPv6 address is its IPv4 address. `client_key` (`app/api/rate_limit.py`) uses it for every rate-limit key; `client_ip` still returns the exact address, which audit and login-history rows store. So every per-IP policy (cart, checkout, storefront lookup, catalogue, auth) groups a subscriber's whole `/64` instead of giving it 2^64 buckets. Cost: clients that share a `/64` (some mobile carriers and VPNs) share a budget.

**3. Scheduled purge.** `POST /internal/carts/purge` (`app/api/v1/internal_cart_purge.py`, service `app/services/store_cart_purge.py`) is called by a QStash schedule and authenticated by the `Upstash-Signature` JWT for exactly that URL (same check as the provisioning callbacks; `PROVISIONING_BASE_URL` and the QStash signing keys must be set, otherwise 503). Each run visits at most `STORES_PER_RUN = 50` ACTIVE stores (a random sample, so all stores are reached over successive runs) and deletes at most `EXPIRED_CARTS_PER_STORE = 1000` expired carts in each (items cascade), skipping rows another transaction has locked (`FOR UPDATE SKIP LOCKED`). A store that cannot be opened or queried, or is still running when the 20 s run budget (`RUN_TIME_BUDGET_SECONDS`) ends, is counted in `stores_failed`, logged by exception class and store id, and does not stop the others. The response is `{stores, carts_deleted, stores_failed}`; an unexpected failure is a 500, so QStash retries. The route is not in the OpenAPI schema and `vercel.json` rewrites `/internal/carts/(.*)` to the backend (like `/internal/provisioning/(.*)`).

### Owner steps

1. Create the schedule once per environment (QStash console or API): destination `https://<PROVISIONING_BASE_URL host>/internal/carts/purge`, method `POST`, no body, cron `0 * * * *` (hourly). Each run visits up to `STORES_PER_RUN = 50` random ACTIVE stores and deletes up to 1000 expired carts in each, so as the number of stores grows, raise the frequency or the constant. Stores that are not ACTIVE (for example suspended) are not purged, retries 3. Nothing else is needed: the signing keys and `PROVISIONING_BASE_URL` already exist for provisioning.
2. After deploying, trigger the schedule once from the console and check the response counts and the `cart purge finished` log line.

### When Redis is unavailable

| Limit | Redis down or too slow | Not configured (local, tests) |
|---|---|---|
| Per-store creation cap | **Fails closed**: a request that would start a cart is refused with **503** `Service temporarily unavailable` and `Retry-After: 5`; nothing is created. Requests with a live token are not affected. The error is logged (exception class only) and reported to Sentry. | Admitted (`DisabledRateLimiter`). |
| `CART_POLICY` (per client IP) | Fails open (warning log, Sentry event). | Admitted. |

The cap fails closed because it protects storage and an outage must not lift it; the price is that shoppers without a cart cannot start one until Redis answers. To fail open instead, set `fail_closed=False` on `CART_CREATE_POLICY`: then `RateLimitedCartCreation` still raises 503 for any limiter error, so change that branch too. Tests: `tests/services/test_store_cart_creation_guard.py` (`test_a_redis_outage_refuses_creation_instead_of_lifting_the_cap`) and `tests/api/test_cart_creation_cap_e2e.py` (`test_with_the_limiter_down_creation_is_refused_but_carts_keep_working`).

## Tests

`tests/api/test_cart_e2e.py` (real Postgres), `tests/api/test_cart_creation_cap_e2e.py` (cap over real routes), `tests/services/test_store_cart.py`, `tests/services/test_store_cart_service.py`, `tests/services/test_store_cart_creation_guard.py`, `tests/services/test_store_cart_purge_e2e.py`, `tests/api/test_internal_cart_purge.py`, `tests/core/test_rate_limit_client_bucket.py`, `src/__tests__/unit/{api/cart,storefront/cart-cookie,app/storefront-cart-routes}.test.ts`, `src/__tests__/e2e/storefront-cart.spec.ts` (needs `E2E_BACKEND_DIR`; seeds stores with `helpers/seed_cart.py`).
