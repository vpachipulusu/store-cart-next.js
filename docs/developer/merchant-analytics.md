# Merchant analytics (KAN-96)

The dashboard page `/dashboard/analytics` shows a store's sales, orders and top products over time. It reads
`GET /v1/stores/{store_id}/analytics` on the backend; the browser never calls FastAPI.

## API

```
GET /v1/stores/{store_id}/analytics?from=YYYY-MM-DD&to=YYYY-MM-DD&bucket=day|week|month
```

- **Who**: OWNER or ADMIN of the organisation that owns the store (`require_merchant(OWNER_ADMIN)`). STAFF get
  403 and the page shows "Analytics are not available for your role". Unknown and foreign stores are the same
  404. Internal key, verified session and the `api` rate limit policy, like the other merchant reads.
- **Range**: `from` and `to` are UTC days, both inclusive. `to` defaults to today (UTC) and `from` to 29 days
  before `to`, so the default is the last 30 days. `from` after `to`, or more than 366 days, is a 422 with a
  plain message. `bucket` defaults to `day`.
- **Response**: `start_date`, `end_date` and `bucket` as applied, and one entry per currency that has sales in the
  range (an empty list when there are none). Each entry has `totals`, a `series` with one point per bucket
  (zeros included, oldest first), `top_products_by_revenue` and `top_products_by_units` (at most 10 each).
  `Cache-Control: no-store`. No caching anywhere.

## Definitions

- **Sale**: an order in `paid`, `fulfilled` or `refunded` status, the statuses an order only reaches after the
  shopper paid. `pending` (unpaid) and `cancelled` orders are never counted.
- **Orders**: the number of sales.
- **Gross sales**: the sum of `orders.total_minor` (lines, shipping and tax added at checkout).
- **Refunds**: the sum of the orders' `order_refunds` rows in `succeeded` status. Pending and failed refunds are
  ignored. A refund counts in the bucket of its order (when the order was placed), not when it was refunded, so a
  bucket's net sales never goes below zero.
- **Net sales**: gross sales minus refunds.
- **Buckets**: by `orders.created_at` in UTC, with Postgres `date_trunc`: calendar days, ISO weeks starting on
  Monday, or calendar months. A bucket is named by its first day, so the first and last week or month can start
  before `from` or end after `to` while only counting orders inside the range.
- **Currencies**: every figure is per order currency, in integer minor units. Amounts are never converted or
  added across currencies. The page formats them with `Intl.NumberFormat` per currency (`formatMinor`).
- **Top products**: grouped by the product name saved on the order line (`order_items.product_name`), so renamed
  or deleted products still show under the name they were sold as; a product's variants are combined. Revenue is
  unit price times quantity as saved on the line (before refunds, without order-level shipping or added tax).
  Ties are broken by the other measure, then by name.

## Implementation

- `app/repositories/store_analytics.py`: two parameterised SQL statements, one round trip each (the sales series
  and the top products, ranked with window functions). Both filter `orders` on status and a `created_at` range,
  which the existing indexes serve (`ix_orders_status_created_at` from store revision 0004 or `ix_orders_created_at`
  from 0005; `tests/api/test_store_analytics_e2e.py` checks the plan). No migration.
- `app/services/store_analytics.py`: the rules above, range defaults and validation, and filling empty buckets.
- `app/api/v1/store_analytics.py`: the route and response models; `store_analytics_service` in `app/api/store_db.py`
  opens the store database through `open_store_session`.
- Frontend: `src/lib/api/analytics.ts` (server-only wrapper), `src/lib/analytics/query.ts` (search params, labels),
  `src/app/dashboard/analytics/` and `src/components/dashboard/analytics/`. The chart is plain CSS bars with the same
  numbers in a table for assistive technology.

## Tests

```bash
cd fastapi_backend
uv run pytest tests/services/test_store_analytics.py
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:<port>/kan96_test uv run pytest tests/api/test_store_analytics_e2e.py
cd ../nextjs-frontend
npm run test:unit -- analytics
npm run test:e2e:local -- merchant-analytics.spec.ts   # needs a backend, see local-e2e.md
```
