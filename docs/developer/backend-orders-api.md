# Backend merchant order API (KAN-79)

List, detail and manual fulfilment of the orders in one store database ([backend-store-orders.md](backend-store-orders.md),
store revisions `0004` and `0005`). Order creation (checkout), payment, cancel and refund routes are other stories.

Code: `app/api/v1/orders.py` (router and schemas), `app/api/store_db.py` (`store_orders_service`, opens the store
database), `app/services/merchant_orders.py` (reads, the fulfil transaction), `app/repositories/store_orders.py` (SQL),
`app/services/store_orders.py` (`fulfil_order`). Tests: `tests/api/test_orders_e2e.py` (real Postgres, needs
`TEST_DATABASE_URL`), `tests/services/test_store_orders*.py`. Frontend: `src/lib/api/orders.ts`,
`src/app/actions/order-actions.ts`, `src/app/dashboard/orders/`; E2E `src/__tests__/e2e/orders-management.spec.ts`.

## Routes

All under `/v1/stores/{store_id}/orders`, called only by the Next.js server (internal key plus verified session, rate
limited by subject). Responses carry `Cache-Control: no-store`; errors use the usual envelope.

| Method and path | Role | Result |
| --------------- | ---- | ------ |
| `GET ""` | any member | page of summaries, newest first: `limit` (1-100, default 25), `offset`, filter `status`; `total` ignores paging. Each row has `item_count` (sum of quantities), `currency`, `total_minor`, `tracking_number`, `carrier`, `fulfilled_at` |
| `GET /{order_id}` | any member | the order with its items (the purchase snapshot), totals, tracking data |
| `POST /{order_id}/fulfil` | OWNER, ADMIN | body `{tracking_number, carrier?}`; moves a `paid` order to `fulfilled`; returns the order |

Errors: 404 `Order not found` (an unknown id and an id of another store are the same), 409 `Only a paid order can be
fulfilled` (it never names the current status), 422 for blank, over-long (100) or control-character tracking text, 403
for STAFF and for a suspended store, 503 `Store database is not available`.

## Tenant isolation

`require_merchant` resolves `{store_id}` against the caller's organisation memberships (foreign and unknown stores are
the same 404) and `store_orders_service` opens the database of the store it resolved. Order ids are looked up only in that
database, so an order id of another store (another organisation or a sibling store) is a 404 and is never changed.
`tests/api/test_orders_e2e.py` probes all three routes with a foreign store, with another store's order id under the
caller's own store, and with a sibling store.

## Out of scope

Customer details, shipping addresses and shipping cost are not in the order model yet. Cancel and refund have no route
(the status flow allows them, see [backend-store-orders.md](backend-store-orders.md#status-flow-ac-2)).
