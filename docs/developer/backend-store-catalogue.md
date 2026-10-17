# Backend store catalogue schema (KAN-70, KAN-71)

Categories and product images (store revision `0003`) are in [their own section](#categories-and-product-images-kan-71) below.

Store revision `0002` (`fastapi_backend/alembic_store/versions/0002_catalogue.py`) adds the catalogue to every store
database. It is a **store** revision (ADR-005, [backend-store-migrations.md](backend-store-migrations.md)); no platform
revision (the platform head stays `0009`). Models only: no API routes yet. Hand-written `op.*` DDL, like all store
revisions (no ORM metadata for the store tree).

| Table | Purpose | Key constraints |
| ----- | ------- | --------------- |
| `products` | title, slug, description, `status` | `slug` unique, lower-case hyphenated (`^[a-z0-9]+(-[a-z0-9]+)*$`, max 200); `status` is `draft` (default) or `active`; title not blank and max 255 |
| `product_options` | an option of a product (Size) | name unique per product, case-insensitive, max 100; cascades with the product |
| `product_option_values` | a value of an option (S, M) | value unique per option, case-insensitive, max 100; cascades with the option |
| `variants` | SKU, price, compare-at price, weight, stock | `sku` unique per store, case-insensitive (`lower(sku)` index), trimmed, max 100; `price_minor >= 0`; `compare_at_price_minor` null or above the price; `weight_grams` null or `>= 0`; `stock >= 0` (default 0) |
| `variant_option_values` | which value a variant has for each option | primary key (variant, option): one value per option; composite foreign keys through `product_id` force the variant, option and value to belong to the same product, and the value to belong to that option |

Delete rules: deleting a product cascades to its options, values, variants and links. Deleting an option or an option
value that a variant still uses is **rejected** (the two link foreign keys are `NO ACTION`, `DEFERRABLE INITIALLY
DEFERRED`), so a variant never silently loses an option; the error appears at commit. They are deferred rather than
immediate because Postgres checks the options before the cascade through variants has removed the links, so an
immediate check would also reject deleting a whole product. Remove or change the variants first.

Decisions:

- **Money** is integer minor units in `bigint` columns (`price_minor`, `compare_at_price_minor`). The currency is a store
  setting, not a variant column. **Weight** is whole grams.
- **Slugs and SKUs are unique per store** because each store has its own database. Lookups by SKU must use
  `lower(sku) = lower(:sku)` to use the unique index; slug lookups use `uq_products_slug` (slugs are stored lower-case).
- **SKU characters:** no control characters (newline, tab) and no leading or trailing space; internal spaces and any
  other characters are allowed. Unicode look-alikes are not normalised.

## Rules the future API and services must follow

- **Deploy:** the revision reaches existing stores only when `commands.migrate_stores` (or the admin migrate endpoint)
  runs after the deploy that ships it ([backend-store-migrations.md](backend-store-migrations.md)). New stores get it
  from the provisioning job.
- **Compare-at price** must be strictly above the price. The API maps "equal" to "no sale" (null) and any violation to
  422. Map constraint violations to 409 (uniqueness) or 422 (value checks).
- **No upper caps** beyond the column types: the API must cap price, compare-at, weight and stock. A `bigint` above
  2^53 loses precision in JavaScript, and an `int` (weight, stock) overflow raises a `DataError`, not an
  `IntegrityError`.
- **Orders and carts** must snapshot title, SKU and price on the line and must not foreign-key cascade from variants.
  There is no `archived` product status yet; adding one means a new `ck_products_status` added `NOT VALID`, then
  `VALIDATE CONSTRAINT`.
- **Service-owned rules** (not in the database): a variant covers every option of its product; no two variants of a
  product share an option combination (lock the product row while checking); `updated_at` is set by the service, there
  is no trigger.
- **Rollback in production means restore, not downgrade.** `downgrade()` drops the catalogue tables with their data and
  exists for local use and tests only.
- Expand-only (new tables), so the previous code version is unaffected while the migration runs.

Tests: `tests/services/test_store_catalogue_schema_e2e.py` migrates a throwaway store database through `migrate_store`
and checks each constraint (needs `TEST_DATABASE_URL`, see [backend-store-migrations.md](backend-store-migrations.md#testing)).

## Categories and product images (KAN-71)

Store revision `0003` (`alembic_store/versions/0003_categories_images.py`) adds three tables. Store tree only; the
platform head stays `0009`. Models only: no API routes yet (the product editor is KAN-73).

| Table | Purpose | Key constraints |
| ----- | ------- | --------------- |
| `categories` | nested categories (adjacency list) | `parent_id` null for a root; `position >= 0` orders siblings (read with `ORDER BY position, id`); `slug` unique per store, lower-case hyphenated, max 200; name not blank, max 255; `parent_id <> id`; index `(parent_id, position)` |
| `product_categories` | product in many categories | primary key (product, category); both foreign keys `CASCADE` (deleting either side removes only the links); index on `category_id` |
| `product_images` | ordered images of a product | `storage_key` unique, shaped `stores/{store_id}/{id}.(jpg\|png\|webp)` (what `MediaUploadService` builds), max 255; `position >= 0`, unique per product and `DEFERRABLE INITIALLY DEFERRED`; `alt_text` max 500; cascades with the product; `created_at` and `updated_at` (set by the service) |

Rules for the future API and services:

- **Deleting a category with children is rejected** (`NO ACTION` on `fk_categories_parent`, checked at the end of the statement); move or delete the children first. One `DELETE` statement may remove a whole subtree.
- **Cycles and depth** are not enforced by the database (only "not its own parent"). The service must reject a move under
  one of the category's own descendants and cap the depth. Do the check and the move in one transaction and lock the
  moved category and its ancestors (`SELECT ... FOR UPDATE`), or two concurrent moves (A under B, B under A) can each pass
  the check and form a cycle.
- **Reordering** (categories or images) renumbers positions in one transaction. Image positions are unique per product but
  the check is deferred, so swapping two positions in a single transaction works. Because it is deferred, a duplicate
  position raises its `IntegrityError` at `COMMIT`, not at the statement (map it to 409 around the commit), and the constraint
  cannot be an `ON CONFLICT` arbiter: use plain `INSERT`/`UPDATE`, never an upsert on `(product_id, position)`. Positions
  have no upper cap in the database: the API must cap them (an `int` overflow raises `DataError`). Categories have no uniqueness on
  position: ties are legal and break by id.
- **R2 objects:** the row stores the object key only; the public URL is `R2_PUBLIC_BASE_URL/{key}`. Deleting a product (or
  an image) removes rows, not objects: the service deletes the R2 objects. The store segment of the key is not checked by
  the database (it does not know its own store id); the service must use the store's id from `MediaUploadService`.
- **Deploy:** reaches existing stores only when `commands.migrate_stores` (or the admin migrate endpoint) runs after the
  deploy. Expand-only, so the previous code is unaffected while it runs. Rollback in production means restore;
  `downgrade()` is for local use and tests.

Tests: `tests/services/test_store_categories_images_schema_e2e.py` (constraints, downgrade to `0002`, and a store at
`0002` with data reaching `0003` through `migrate_store`).
