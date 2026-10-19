# Server-side cart (KAN-76)

Shoppers keep a cart per store. Only the Next.js server calls the backend (D14); the browser calls the storefront host.

## Flow

Browser → `{slug}.<root>/cart[/items[/{variantId}]]` (Next.js route handlers under `src/app/storefront/[slug]/cart/`, store hosts only) → `src/lib/api/cart.ts` → `/v1/storefront/{slug}/cart` (FastAPI).

| Route | Effect |
|---|---|
| `GET /cart` | The cart, priced now. No cart reads as empty and creates nothing. |
| `POST /cart/items` `{variant_id, quantity}` | Adds to the quantity in the cart; starts a cart when there is none. |
| `PUT /cart/items/{variant_id}` `{quantity}` | Sets the quantity. |
| `DELETE /cart/items/{variant_id}` | Removes the line. |

## Store-scoped cookie

The cart token (32 random bytes, 43 url-safe chars) lives in an httpOnly, SameSite=Lax cookie named `sc_cart_<slug>` (`__Host-sc_cart_<slug>` in production, which also blocks cookie tossing from sibling subdomains). It is host-only on a store subdomain, 30 days. The backend stores only its SHA-256 (`carts.token_hash`) and returns the token once, in `cart_token`, when a write starts a cart; `src/lib/api/cart.ts` sets the cookie and never passes the token on. Each store has its own database, so a token or variant id from one store is nothing in another.

## Prices and stock are re-checked every time

`cart_items` holds only `variant_id` and `quantity`. Every response re-reads name, price, stock and product status from the catalogue and recomputes totals with `compute_totals` (store shipping and tax settings). A line is `ok`, or `unavailable` (product no longer active), `out_of_stock` or `limited` (quantity above stock); only `ok` lines count in the totals and `can_checkout` needs every line `ok`. Writes refuse a variant that is not sellable or a quantity above stock (409 "Only N in stock"). Stock is not reserved. The client can name only a variant and a quantity (1 to 99, at most 50 lines).

## Notes

- Migration: store `0007_carts` (expand-only). Carts expire 30 days after the last write; up to 20 expired carts are purged when a new cart is created.
- Rate limit: `CART_POLICY`, 60/min per client IP, fails open. Cart creation is not limited per store; a scheduled purge and a per-store creation limit are not part of this story.
- `/s/{slug}` path preview does not serve cart routes (store hosts only).
- Tests: `tests/api/test_cart_e2e.py` (real Postgres), `tests/services/test_store_cart.py`, `src/__tests__/unit/{api/cart,storefront/cart-cookie,app/storefront-cart-routes}.test.ts`, `src/__tests__/e2e/storefront-cart.spec.ts` (needs `E2E_BACKEND_DIR`; seeds stores with `helpers/seed_cart.py`).
