# Backend product API (KAN-245)

Merchant CRUD for products, variants and image rows over the per-store catalogue tables
([backend-store-catalogue.md](backend-store-catalogue.md), store revisions `0002` and `0003`). No store migration was
added. No browser upload and no storefront reads (KAN-75), plan limits (KAN-84) or merchant UI (KAN-73/74) here.

Code: `app/api/v1/products.py` (router and schemas), `app/api/store_db.py` (opens the store database),
`app/services/store_products.py` (transactions), `store_product_rules.py` (validation, pure), `store_product_types.py`
(limits, errors, data shapes), `app/repositories/store_catalogue.py` (SQL). Tests: `tests/api/test_products_e2e.py`,
`test_products_isolation_e2e.py` (real Postgres, need `TEST_DATABASE_URL`) and `tests/services/test_store_product_rules.py`.

## Routes

All under `/v1/stores/{store_id}/products`, called only by the Next.js server (internal key plus verified session, rate
limited by subject). Responses carry `Cache-Control: no-store`; errors use the usual envelope.

| Method and path | Role | Result |
| --------------- | ---- | ------ |
| `GET ""` | any member | page of summaries: `limit` (1-100, default 25), `offset`, filters `status`, `category_id` and `q` (text search, see below); `total` ignores paging |
| `POST ""` | OWNER, ADMIN | 201, the product with its options and variants (a product needs at least one variant) |
| `GET /{product_id}` | any member | the product: options, values, variants, `category_ids`, images |
| `PATCH /{product_id}` | OWNER, ADMIN | title, slug, description (null clears), status, `category_ids` (replaces the set) |
| `DELETE /{product_id}` | OWNER, ADMIN | 204; removes variants, images and links |
| `POST /{product_id}/variants` | OWNER, ADMIN | 201, the product |
| `PATCH /{product_id}/variants/{variant_id}` | OWNER, ADMIN | sku, price, compare-at, weight, stock |
| `DELETE /{product_id}/variants/{variant_id}` | OWNER, ADMIN | the product; the last variant cannot be deleted (422) |
| `POST /{product_id}/images` | OWNER, ADMIN | 201, the product; records a row for an uploaded object |
| `DELETE /{product_id}/images/{image_id}` | OWNER, ADMIN | the product; removes the row only |

Categories (KAN-246) are on their own prefix: `GET /v1/stores/{store_id}/categories` (any member, same store resolution
and `no-store`) returns `{"data": [{id, name, slug, parent_id, position}], "truncated": false}`. Order is roots first,
then by parent, `position`, `id` (siblings stay together); at most 1000 rows, `truncated` is true when the store holds
more. The list is flat, not depth-first: a client builds the tree from `parent_id`. There is no write route here (405).

## Search (KAN-246)

`GET ""` takes `q`: trimmed, blank means no search, at most 100 characters after trimming (422 above, and for a NUL
character). It matches when the product **title** or **any variant SKU** contains the text, ignoring case (`ILIKE`
with an explicit escape character). `%`, `_` and `\` in `q` are literal: the text is escaped in
`search_pattern` and sent as one bound parameter, never concatenated into SQL. It combines with `status` and
`category_id` (all must match); `total`, `limit` and `offset` behave as before, and the order is still newest first.
It is a sequential scan per store (no index added, no migration); fine for the catalogue sizes the plan limits allow; a `pg_trgm` index (a store migration) is the option if that changes.
Tests: `tests/api/test_products_search_e2e.py`.

Writes also need an ACTIVE store (`require_merchant`: any non-GET is a write). Reads work on SUSPENDED and PROVISIONING
stores. Every response holds the platform `currency` setting (money has no currency column).

## Which store is used

`{store_id}` is resolved by `require_merchant` against the caller's own organisation memberships, read from the platform
database on every request: an unknown, foreign or archived store is the same 404 `Store not found`. The database that is
opened is that of `merchant.store.id` (the id read back from the platform row), through `open_store_session`, the only
door to a store database (`get_store_session` with the platform session provider as the injectable seam; no engine is
created here). Bodies reject unknown fields, so a store id in the body is a 422. A store without a connection string or
with an unusable one answers a fixed 503 `Store database is not available` (the cause is logged with the store id, never
the connection string).

A product, variant or image id from another store, or another product, is a plain 404 (`Product not found`, `Variant
not found`, `Image not found`): the SQL runs on the caller's store database only, and variant and image queries also
filter by product id.

## Rules

- **Money** is integer minor units; price, compare-at at most 2^53-1 (JavaScript safe), weight at most 1,000,000,000 g,
  stock at most 1,000,000,000. Compare-at equal to the price is stored as null ("no sale"); below it is 422.
- **Slug** lower-case hyphenated, at most 200; derived from the title when omitted (ASCII-folded), 409 when taken. **SKU**
  trimmed, 1-100, no control characters, unique per store ignoring case (409; the same SKU may exist in another store).
- **Options and variants**: at most 3 options with 1-50 values each, at most 100 variants. A variant names one value of
  every option (`"options": {"Size": "M"}`, matched ignoring case); no two variants share a combination (409 when adding;
  422 inside one create). The product row is locked (`FOR UPDATE`) while checking, so concurrent adds cannot both win.
  A product without options has exactly one variant. Options and values cannot be edited after creation (not in this
  story).
- **Categories** must exist in the same store (422 `Unknown category`), at most 50.
- **Archive** is `status: "draft"` (unpublish). There is no archived status: that would need a store revision.
- **Delete** keeps orders intact: `order_items` snapshot name, SKU and price and their links are `ON DELETE SET NULL`
  (see [backend-store-orders.md](backend-store-orders.md)). The R2 objects of removed images are not deleted.
- **Images**: `storage_key` must be exactly `stores/{store_id}/{id}.(jpg|png|webp)` for the caller's store
  (`image_key_for_store`; the id segment is `[A-Za-z0-9_-]+`, no further path segments, at most 255 characters), otherwise
  422 `Image key does not belong to this store`. This is checked before the database, which also enforces the shape
  (`ck_product_images_storage_key`). The object's existence is not checked. The same key cannot be attached twice (409),
  at most 20 images per product, positions are appended (`max + 1`). Presign with `POST
  /v1/stores/{store_id}/uploads/images`; the public URL is `R2_PUBLIC_BASE_URL/{storage_key}`.
- **Errors are curated**: 404, 409 and 422 carry fixed messages. Constraint names are mapped to messages in
  `store_product_rules.CONFLICTS`; any other database error rolls back and becomes the generic 500 (logged, never shown).
  Deferred constraints fail at `COMMIT`, which sits inside the same translation.

## Adding a route

Use `store_products_service()` (all roles) or `store_products_service(OWNER_ADMIN)` as the dependency, never open a store
session in the router, and add the route to the probe lists in `test_products_isolation_e2e.py` so it is checked against
a foreign store, a foreign id and a sibling store. `tests/services/test_store_session_callers.py` lists the modules
allowed to open a store database.

## Plan limit (KAN-84)

`POST` is refused with 409 when the store already holds the plan's `max_products`; see [backend-plan-limits.md](backend-plan-limits.md).
