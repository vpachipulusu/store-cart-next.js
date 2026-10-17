# Backend store catalogue schema (KAN-70)

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

Decisions:

- **Money** is integer minor units in `bigint` columns (`price_minor`, `compare_at_price_minor`). The currency is a store
  setting, not a variant column. **Weight** is whole grams.
- **Slugs and SKUs are unique per store** because each store has its own database. Lookups by SKU must use
  `lower(sku) = lower(:sku)` to use the unique index; slug lookups use `uq_products_slug` (slugs are stored lower-case).
- **Not enforced in the database:** that a variant covers every option of its product, and `updated_at` (server
  default only; the writing service sets it on update). The service that writes products (a later story) owns those
  rules and must map constraint violations to 409/422.
- Expand-only (new tables), so the previous code version is unaffected while the migration runs.

Tests: `tests/services/test_store_catalogue_schema_e2e.py` migrates a throwaway store database through `migrate_store`
and checks each constraint (needs `TEST_DATABASE_URL`, see [backend-store-migrations.md](backend-store-migrations.md#testing)).
