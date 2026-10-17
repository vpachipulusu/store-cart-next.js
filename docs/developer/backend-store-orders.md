# Backend store orders (KAN-78)

Store revision `0004` adds `orders` and `order_items` to every store database (ADR-005). The service is
`app/services/store_orders.py`. There are no HTTP routes yet (no OpenAPI change); the checkout and order-management
stories add them.

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

## Tests

`tests/services/test_store_orders.py` (rule matrix, tax rounding, no database), `test_store_orders_schema_e2e.py`
(constraints, snapshot survival, SET NULL, downgrade, upgrade of a populated 0003 store) and
`test_store_orders_e2e.py` (service through `open_store_session`, racing transitions, isolation between two stores).
The e2e files need `TEST_DATABASE_URL` (see [backend-store-migrations.md](backend-store-migrations.md#testing)).
