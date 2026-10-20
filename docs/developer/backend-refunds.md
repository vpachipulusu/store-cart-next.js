# Backend merchant refunds (KAN-80)

A merchant refunds a paid or fulfilled order in full or by lines. Money moves on the merchant's connected account
(direct charges, plan D4); the order, the refund and the optional restock are recorded in the store database.
Code: `app/services/store_refunds.py` (SQL rules), `app/services/merchant_order_refund.py` (orchestration),
`app/core/stripe_refunds.py` (Stripe call), `app/api/v1/order_refunds.py` (route).

## Route

`POST /v1/stores/{store_id}/orders/{order_id}/refunds`, OWNER or ADMIN, ACTIVE store, internal key, per-subject rate
limit (same access as fulfil).

```json
{ "items": [{ "order_item_id": "…", "quantity": 1 }], "restock": false }
```

- `items` omitted: refund everything that remains, shipping included. With `items`: those lines only (shipping is
  refunded by a full refund only). Each line's amount is `unit_price × q` plus, when prices exclude tax, `tax × q ÷ line
  quantity` taken cumulatively, so the parts of a line add up to the line to the minor unit.
- `restock` (strict boolean, **default false**) is the merchant's choice per refund. Only when true are the refunded
  quantities returned to variant stock.
- Response: the order (`OrderData`) with `refunded_minor` (sum of succeeded refunds) and `refunds[]` (`id`,
  `amount_minor`, `currency`, `status` `pending|succeeded|failed`, `restock`, `restocked_at`, timestamps).
- Errors: 404 unknown order or store; 403 STAFF; 409 not paid, no payment, more than remains, nothing left, or refused
  by Stripe; 422 invalid lines (an item of another order, duplicates, quantity); 502 the outcome is unknown (do not
  repeat the request, read the order); 409 also when the organisation has no connected account; 503 Stripe not configured.

## Life of a refund

1. **Reserve** (`reserve_refund`, one transaction, commit): lock the order row, check what remains, insert a `pending`
   refund with its lines. Pending and succeeded refunds both count against the order, so two concurrent requests cannot
   refund the same units or money.
2. **Ask Stripe** (no transaction open): `POST /v1/refunds` on the connected account with `payment_intent`, `amount`,
   metadata `store_id`, `order_id`, `refund_id`, idempotency key `refund-<refund id>`. The platform application fee is
   not refunded (owner decision pending).
3. **Settle** (`settle_refund`): Stripe's answer, or the `refund.created|updated|failed` Connect webhook, settles the
   refund **once**: one conditional `UPDATE … WHERE status = 'pending'` under the order's row lock decides the winner, so
   the API response and the webhook can race, and a replayed or concurrent event changes nothing. `succeeded`: restock
   (if asked) in the same transaction, and the order moves to `refunded` when succeeded refunds add up to its total.
   `failed`/`canceled`, or a definite refusal when asking Stripe: the refund becomes `failed` and frees what it held.

An unknown outcome (timeout, 5xx, in-flight idempotency key) leaves the refund `pending` and returns 502: the refund may
still happen, so nothing is released. If Stripe did create it, the webhook settles it. A webhook must agree with our row
(order, amount, currency, payment intent, Stripe refund id) or nothing changes and the event goes to Sentry.

## Restock rules

- Default off; per refund; only when the refund **succeeds**; never before.
- Returns at most `order_items.stock_taken − restocked_quantity` per line. `stock_taken` is written by
  `take_paid_stock` (KAN-72) when the order is paid: the whole line, or 0 when stock could not cover it (oversold) or the
  variant was deleted. So an oversold line's never-taken units are never added back, a partial refund returns only the
  refunded quantities, and refunds together can never return more than the order took.
- A line whose variant was deleted (`variant_id` NULL) is skipped.
- Orders paid before revision `0011` have `stock_taken = 0` and are never restocked by a refund (whether they took
  stock is unknown; orders paid before `0010` never did).

## Schema (store revision `0011_order_refunds`)

Expand-only. `order_items.stock_taken`, `order_items.restocked_quantity` (checked `0 ≤ restocked ≤ taken ≤ quantity`);
tables `order_refunds` (status, amount, `restock`, `restocked_at`, unique `stripe_refund_id`) and
`order_refund_items`. **Owner steps:** run `migrate-stores` so every store reaches `0011` before deploying this code
(the paid path writes `stock_taken`), and add `refund.created`, `refund.updated` and `refund.failed` to the events of
the Stripe **Connect** webhook endpoint.

## Known limits

- A refund made in the Stripe dashboard has no `refund_id` metadata and is acknowledged and ignored (the order is not
  updated).
- A refund stuck `pending` because Stripe never created it (outcome unknown, no webhook) stays reserved and blocks
  those units and that money: there is no retry, cancel or reconcile path yet. Re-sending with the same refund id is safe
  (the idempotency key is the refund id), so a retry endpoint or sweeper is the follow-up (sized work, owner decides).
- A refund that Stripe fails after reporting success is not reversed: the event is not applied and goes to Sentry
  (`UnappliedRefundEvent`) for a person to resolve.
- Orders paid between the `0010` deploy and `0011` took stock but have `stock_taken = 0`, so refunding them with
  `restock` returns nothing; restock those by hand.
- No `refund_application_fee`: the platform keeps its fee on refunded payments.

Tests: `tests/services/test_store_refunds_e2e.py` (reserve, settle, restock, concurrency, oversold, deleted
variants), `tests/api/test_order_refunds_e2e.py` (route, webhook, Stripe failures, roles), `tests/core/test_stripe_refunds.py`.
Real Postgres tests need `TEST_DATABASE_URL` (see [backend-auth.md](backend-auth.md)).
