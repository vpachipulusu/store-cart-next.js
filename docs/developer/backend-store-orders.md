# Backend store orders (KAN-78)

Store revision `0004` adds `orders` and `order_items` to every store database (ADR-005). The service is
`app/services/store_orders.py`. The merchant routes (list, detail, fulfil) were added by KAN-79, see [backend-orders-api.md](backend-orders-api.md);
the checkout story adds order creation.

## Tables

| Table | Notes |
| ----- | ----- |
| `orders` | `status` (default `pending`), `currency` (ISO 4217, upper case), `subtotal_minor`, `tax_minor`, `total_minor` |
| `order_items` | one row per purchased variant: the snapshot plus nullable links back to the catalogue |

- Money is integer minor units (bigint). `total_minor = subtotal_minor + tax_minor` is a CHECK. The currency is stored
  on the order because the store setting can change after purchase.
- **Snapshot (AC 1).** An item stores `product_name`, `sku`, `variant_label` (option values joined with ` / `, for
  example `Large / Red`), `unit_price_minor`, `quantity`, `tax_rate_bps` (basis points, 2000 = 20%) and `tax_minor`.
  Nothing is read back from the catalogue after purchase. Tax per line is `unit * quantity * rate`, rounded half up in
  integer arithmetic; the order totals are the sums of the lines.
- `product_id` and `variant_id` are nullable and `ON DELETE SET NULL`, so deleting or editing a catalogue row never
  changes or removes an order line. Deleting an order removes its items.
- One line per variant and order: a partial unique index on `(order_id, variant_id)` (lines whose variant was deleted are exempt).
- `create_order` share-locks the sold variant and product rows (`FOR SHARE`) until the caller's transaction ends, so a concurrent price edit, unpublish or delete cannot land between the read and the insert. The service is the only writer of order money columns; there is no update path.
- Limits (CHECKs): quantity 1 to 10000, tax rate 0 to 100000 bps, product name at most 255 characters, SKU 1 to 100.

## Status flow (AC 2)

```
pending -> paid -> fulfilled
pending -> cancelled
paid    -> cancelled
paid    -> refunded
fulfilled -> refunded
```

`cancelled` and `refunded` are final; nothing moves backwards. The database CHECK only limits the set of values. The
transition rule is `ALLOWED_TRANSITIONS` in the service, applied by `transition_order` with one conditional
`UPDATE ... WHERE status IN (allowed sources)`, so two concurrent moves cannot both succeed from the same status. A
rejected move raises `InvalidOrderTransition`, an unknown id `OrderNotFound`. Do not write `orders.status` anywhere else.

## Using the service

```python
async with get_store_session(store_id) as session:
    order = await create_order(session, currency="GBP", tax_rate_bps=2000,
                               lines=[OrderLineInput(variant_id=variant_id, quantity=2)])
    await transition_order(session, order.id, OrderStatus.PAID)
    await session.commit()
```

- The service never commits and never opens a session; the caller owns the transaction. A failed `create_order`
  writes nothing.
- `create_order` only sells variants of `active` products; one error ("An item is not available") covers missing and
  draft so a draft's existence is not revealed.
- The tax rate is a parameter because no store tax setting exists yet. Stock is not decremented here (inventory story).
- A route that exposes an order id must authorize the store id itself (the selected-store cookie is a preference).

## Fulfilment (KAN-79, revision `0005`)

Revision `0005` adds three nullable columns to `orders`: `tracking_number`, `carrier` (1 to 100 characters when set)
and `fulfilled_at`. The CHECK `ck_orders_fulfilled_tracking` says a `fulfilled` order always has a tracking number
(the columns stay set if a fulfilled order is later refunded).

`fulfil_order(session, order_id, tracking_number, carrier=None)` is the **only** way to reach `fulfilled`: one
conditional `UPDATE ... WHERE status = 'paid'` writes the status, the (trimmed) tracking number, the carrier and
`fulfilled_at` together, so two concurrent fulfilments cannot both succeed. `transition_order(..., FULFILLED)` raises
`InvalidOrder`, because the CHECK would reject it anyway. Errors are the same as for `transition_order`
(`OrderNotFound`, `InvalidOrderTransition`) plus `InvalidOrder` for tracking text that is blank, over 100 characters or
has control characters.

## Stock and oversell protection (KAN-72, revision `0010`)

Stock lives on `variants.stock` (CHECK `stock >= 0`). It is not reserved by a cart or a `pending` order; it is taken
**only when an order becomes `paid`**. `mark_checkout_paid` calls `take_paid_stock(session, order_id)` right after its
conditional `UPDATE ... status = 'paid'` succeeded, in the same transaction, so:

- A webhook retry (`ALREADY_PAID`), a mismatch or an unknown order never touches stock, and a rolled-back payment
  update rolls the stock back with it.
- Each line is one `UPDATE variants SET stock = stock - :n WHERE id = :v AND stock >= :n` (never read then write).
  Concurrent orders for the last unit queue on the row lock; the loser re-checks and finds too little. Lines go in
  variant id order so two orders cannot deadlock.
- A line that stock cannot cover, or whose variant was deleted (`order_items.variant_id` is NULL), is left untaken. The
  order **stays `paid`** (the shopper was charged), `orders.oversold` is set to true, an error is logged with the order
  and item ids and an `OversoldOrder` event goes to Sentry. The webhook still succeeds. Other lines of the same order
  are still taken (`order_items.stock_taken` records which), so a refund with `restock` returns only what was taken (KAN-80,
  [backend-refunds.md](backend-refunds.md)).
- `oversold` is returned by the merchant order API (list and detail). Resolving it (fulfil late, or refund and restock)
  is the merchant's job; refunds and the optional restock are KAN-80 ([backend-refunds.md](backend-refunds.md)), and
  cancelling a paid order does not restock.

Revision `0010` adds `orders.oversold boolean NOT NULL DEFAULT false` and the partial index `ix_orders_oversold`
(expand-only; existing orders get false because stock was never decremented before). Downgrade drops both.

## Rules for callers (checkout and order routes)

- **Totals are enforced by the service only.** The database checks `total = subtotal + tax` on the order row, but nothing
  links the order totals to the item rows. `create_order` is the only writer; add no other path that writes money
  columns.
- **Commit promptly after `create_order`.** The row lock (`FOR SHARE`) is held until the caller's transaction ends. A
  pending order's price is only as fresh as that transaction; it is a snapshot, not a reservation.
- **Reuse the per-line tax rule.** Tax is `round_half_up(unit * quantity * rate_bps / 10000)` per line, then summed.
  Checkout and any display of totals must use `line_tax_minor`, not round the order total.
- **Never return the `InvalidOrderTransition` message to clients.** It names the current status. Map it to a fixed 409
  message; map `OrderNotFound` to a fixed 404 (the exception message carries the id).
- `order_items` has `created_at` only: items are immutable snapshots and have no `updated_at`.
- `pending` and `paid` may race with `cancelled`: paid then cancelled is a legal sequence, so a payment webhook and a
  merchant cancel arriving together can both succeed, ending `cancelled`. Refund the payment in that case.

## Tests

`tests/services/test_store_orders.py` (rule matrix, tax rounding, no database), `test_store_orders_schema_e2e.py`
(constraints, snapshot survival, SET NULL, downgrade, upgrade of a populated 0003 store) and
`test_store_inventory_e2e.py` (KAN-72: decrement on paid, retry, mismatch, short and deleted lines, racing orders), `test_store_oversold_schema_e2e.py` (migration 0010) and
`test_store_orders_e2e.py` (service through `open_store_session`, real concurrent transitions with `asyncio.gather`, the `FOR SHARE` lock, limits at their boundaries, isolation between two stores).
The e2e files need `TEST_DATABASE_URL` (see [backend-store-migrations.md](backend-store-migrations.md#testing)).
