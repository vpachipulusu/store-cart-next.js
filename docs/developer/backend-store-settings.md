# Store settings: shipping and tax (KAN-82, KAN-83)

**Last updated:** 2026-10-19

Each store database holds one `store_settings` row (store migration `0005`): a flat shipping rate, an optional free-shipping threshold, a manual tax rate and whether prices include tax. Money is integer minor units in the platform currency; the tax rate is in basis points (2000 = 20%, at most 10000).

| Column                          | Meaning                                                               | Range                |
| ------------------------------- | --------------------------------------------------------------------- | -------------------- |
| `shipping_flat_rate_minor`      | Charged once per order                                                | 0 to 100 000 000 000 |
| `free_shipping_threshold_minor` | Item subtotal at or above which shipping is free; `NULL` = never free | 1 to 100 000 000 000 |
| `tax_rate_bps`                  | Tax rate                                                              | 0 to 10000           |
| `prices_include_tax`            | Catalogue prices already contain the tax                              | true / false         |

The row is a singleton (boolean primary key forced true) seeded by the migration with no shipping, no threshold, no tax and prices excluding tax. The repository re-creates it if a support script ever deletes it.

## API

`GET /v1/stores/{store_id}/store-settings` (any member) and `PATCH` (OWNER or ADMIN, ACTIVE store). Resolved like the product routes: unknown and foreign stores are the same 404, the store database comes from the membership. `PATCH` changes only the fields sent; `free_shipping_threshold_minor: null` removes the threshold; `null` on any other field, an unknown field or an out-of-range value is a 422. Responses carry `Cache-Control: no-store`. Changes are logged with the store id and field names, not values.

## Totals (`app/services/store_totals.py`)

`compute_totals(lines, TotalsSettings)` is pure and works in minor units:

- **Shipping:** the flat rate, or 0 when the item subtotal (as priced, before any tax added on top) reaches the threshold. An empty basket, or one whose items are all free, ships nothing.
- **Tax** applies to items, not shipping, per line. Prices excluding tax: tax is rounded half up per line and added to the total. Prices including tax: the net is rounded half up, the tax is the rest (so net + tax = gross), and the total is `subtotal + shipping`.
- A total above the bigint limit raises `ValueError`.

`StoreSettingsService.totals_settings()` returns the `TotalsSettings` of a store. **The order flow (`store_orders.create_order`, KAN-79) does not call this yet**: it still takes a caller-supplied tax rate and has no shipping column. Wiring it, and storing shipping on the order, belongs with the orders work.

## Frontend

`/dashboard/settings/store` ("Shipping and tax" in the nav) shows the form: amounts in the store currency's major units, the tax rate as a percentage. Parsing is string-based (`src/lib/store-settings/form.ts`); the server action sends minor units and basis points for the server-selected store.

Tests: `tests/services/test_store_totals.py`, `test_store_settings.py`, `test_store_settings_schema_e2e.py`, `tests/api/test_store_settings_e2e.py` (real Postgres via `TEST_DATABASE_URL`), the Vitest suites `store-settings*.test.*`, and `src/__tests__/e2e/store-settings.spec.ts` (local only, `docs/developer/local-e2e.md`).
