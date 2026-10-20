# Storefront checkout on the merchant's connected account (KAN-68)

**Last updated:** 2026-10-20

A shopper's cart becomes a `pending` order priced only on the server, and a Stripe Checkout Session created as a **direct charge** on the store organisation's connected account (KAN-67). The Connect webhook (KAN-69) marks the order `paid`. The storefront UI that calls this is KAN-77.

## API

`POST /v1/storefront/{slug}/checkout` (internal service key, no user session, `CHECKOUT_POLICY` 10/min per client IP and **fail closed**: 503 when the rate limiter is down, KAN-256; `Cache-Control: no-store`). The cart token travels in `X-Cart-Token`, like the cart routes ([backend-storefront-cart.md](backend-storefront-cart.md)).

| Body | Rule |
|---|---|
| `success_url`, `cancel_url` | Required. The origin must be on `BILLING_RETURN_URL_ORIGINS`, or be the store's own host `https://{slug}.<PLATFORM_ROOT_DOMAIN>` (for example `https://shop.storecart.com`). The store host is also allowed with the scheme and port of an app origin on the root domain (`http://localhost:3000` with root `localhost` allows `http://{slug}.localhost:3000`). Unset or invalid `PLATFORM_ROOT_DOMAIN` allows only the app origins. Anything else is 422. |
| anything else | 422. The client can never send an amount, a price or a line. |

Answer: `{order_id, checkout_url}`; redirect the shopper to `checkout_url` (Stripe-hosted). Errors (generic text, no Stripe output): 404 store not found (unknown, not ACTIVE), 409 "Payments are not enabled for this store" (no connected account or charges off; nothing is written), 409 cart empty or changed (a line unavailable, out of stock or above stock, or the catalogue changed between the cart view and pricing), 409 "Your payment is being processed" (the cart's earlier session was already paid), 422 return URL, 502 Stripe failed or the organisation's `platform_fee_bps` is outside 0..10000 (refused before anything is written), 503 `STRIPE_SECRET_KEY` unset, store database unavailable, or the rate limiter down (fail closed).

## One open order per cart (KAN-256)

A cart has at most one `pending` checkout order. The database enforces it: `orders.cart_id` and a partial unique index `uq_orders_open_checkout_per_cart` on `cart_id` where `status = 'pending'`. Each order also stores `checkout_fingerprint` (a hash of the lines, unit prices, total, currency and both return URLs), `stripe_checkout_url` and `checkout_expires_at`.

`StoreCheckoutService.start` looks at the cart's open order first:

| Open order | Result |
|---|---|
| none | write a new order, create its session |
| same fingerprint, more than 5 minutes (`REUSE_MARGIN`) from its end, has a URL | return that URL: no new order, no new Stripe call (a double click, a second tab) |
| same fingerprint, no URL (the first start never learned its session), at least 31 minutes (`RESUME_MIN_REMAINING`) left | create the session again for the same order. The idempotency key is the order's, `expires_at` is the stored one and the line items are sent in a stable order (variant id, name, SKU), so Stripe returns the session it may already have made instead of rejecting the key's changed parameters |
| different fingerprint (cart, prices or return URLs changed) or at the end of its life (inside the margin, or expired) | expire its Stripe session, then cancel the order, then write a new order. The old session is closed first so a payable session is never left behind a cancelled order |

If the old session cannot be expired (Stripe down) the answer is 502 and nothing changes. If it turns out to be `complete` the answer is 409 and the order stays `pending` for the webhook. An old order whose session id is unknown and that has not expired yet may still have a session at Stripe, so it is neither cancelled nor replaced (502) until it expires. Two requests racing for the same cart both reach the unique index; the loser looks again and reuses the winner's order (up to 3 attempts).

## How the amounts are made

1. The cart must be checkout-ready (`can_checkout`).
2. `price_checkout_order` (`app/services/store_checkout.py`) re-reads each variant from the catalogue under `FOR SHARE` and prices it with `compute_totals` and the store settings (KAN-82/83): subtotal, shipping, tax (added on top, or included in prices) in integer minor units. The order stores `shipping_minor` and `prices_include_tax`, and the database checks `total = subtotal + shipping + (tax unless included)`.
3. The session's line items are the order lines, then a `Tax` line (only when tax is added on top) and a `Shipping` line; their sum must equal the order total or nothing is sent. Currency is the platform currency setting.

## Stripe call

`POST /v1/checkout/sessions` with `Stripe-Account: acct_...` (direct charge: the merchant is the merchant of record; the payment, Stripe's fees, disputes and refunds are on their account), `mode=payment`, an explicit `expires_at` (`SESSION_LIFETIME` = 60 minutes: Stripe requires 30 minutes to 24 hours after creation, and the long window is what lets a start that never learned its session be resumed (it needs 31 minutes left); stored as `checkout_expires_at`), `metadata[store_id]`, `metadata[order_id]` (also on the PaymentIntent), `client_reference_id` = order id. Idempotency key `sc-checkout-{store_id}-{order_id}`, built on the server. A request Stripe did not process (400, 401, 402, 403, 404, 429) cancels the order. An unknown outcome (timeout, transport error, 5xx, 409 in flight) is retried once with the same key, after a 0.5 s pause for a 409. The retry really helps after a timeout or transport error, where Stripe answers with the session it may already have made rather than a second one; a 5xx is usually replayed as is. If the outcome is still unknown the order stays `pending` (cancelling it could leave a live session whose payment is never applied) and the answer is 502. A failure while building the request after the order was written (a line-sum mismatch) cancels the order too. If linking the session to the order fails after Stripe succeeded, the URL is still returned: the webhook accepts an order with no session linked yet.

**Platform fee.** `payment_intent_data[application_fee_amount]` = `round_half_up(total * organizations.platform_fee_bps / 10000)`, on the amount charged (items, tax added on top and shipping). `platform_fee_bps` defaults to 0 (decision D9: subscription revenue only), and then the field is **not sent**. Raising the column for an organisation turns the fee on with no code change. The fee code is `platform_fee_minor`.

## Confirmation (Connect webhook)

Registered store handlers: `checkout.session.completed` and `checkout.session.async_payment_succeeded` (`checkout_payment_handler`, wired in `app/api/v1/webhooks_connect.py`). KAN-69 has already checked the signature, the mode (`livemode` must match the platform key, otherwise ignored), the event id (once only) and that `metadata.store_id` is a store of the account's organisation.

- Only `payment_status = paid` moves anything; `completed` with `unpaid` (a delayed payment method) waits for `async_payment_succeeded`.
- `mark_checkout_paid` is one conditional `UPDATE`: the order (from `metadata.order_id`) must be `pending`, linked to this session or none yet, and `amount_total`/`currency` must equal its total and currency. A session already linked to another order never pays this one (`stripe_checkout_session_id` is unique).
- An event whose route has no store (cannot happen for store-scoped types) is logged and reported, not dropped silently.
- `metadata.order_id` picks the order (KAN-69's rule is to trust metadata only to pick the store). That is safe here because only the platform can create sessions on an Express account (the merchant has no API keys), and the update still requires the order's own amount, currency and session, so a forged id cannot pay a different order.
- Store-database writes are at least once (KAN-69): a rerun or a concurrent delivery finds the order paid and changes nothing. Mismatches (amount, currency, another session, a cancelled order) and paid sessions without usable fields are logged as errors, reported to Sentry (`UnappliedCheckoutPayment`) and acknowledged; a paid session for a cancelled order needs a manual refund in the merchant's dashboard.

## Expiry of unpaid orders (KAN-256)

- **`checkout.session.expired` and `checkout.session.async_payment_failed`** (Connect webhook, `checkout_expired_handler` in `app/services/store_checkout_expiry.py`, registered in `get_connect_webhook_service`) cancel the order linked to that session while it is still `pending` (a failed delayed-method payment ends the session for good; without this its order would hold the cart's one open-order slot and block every retry): one conditional `UPDATE`, so a redelivery, a paid order and a session linked to another order change nothing.
- **Sweep backstop** (`sweep_expired_checkout_orders`): looks at pending orders more than `SWEEP_GRACE` (10 min) past `checkout_expires_at`, oldest first, in pages with a cursor. An order with no session id is cancelled. An order with one is cancelled only after Stripe confirms the session is expired (`expire_session` answers `EXPIRED`); a `complete` session (a delayed payment method still settling, or a payment webhook that has not arrived) and any order the sweep cannot verify (Stripe error, no connected account, no `STRIPE_SECRET_KEY`) stay `pending` for their payment event. No transaction is held across a Stripe call. Each checkout start sweeps up to 5 stale orders **without a session id** of its own store (best effort, no Stripe call on a shopper's request; orders with a session are the command's job, so stuck ones cannot starve it); `uv run python -m commands.sweep_checkout_orders [--batch-size N]` pages through every ACTIVE store (up to 10 pages of `--batch-size`, default 200, per store, within a 240 s time budget for the whole run, so the Stripe calls per run are bounded; exit 1 if a store failed) and needs `STRIPE_SECRET_KEY` for orders that have a session. No schedule is configured: run it from a cron or a manual workflow if you want stores that see no checkout to be swept too.
- The webhook handler does not call Stripe: Stripe itself says the session expired.

## Merchant cancel (KAN-256)

`POST /v1/stores/{store_id}/orders/{order_id}/cancel` (OWNER or ADMIN, ACTIVE store; see [backend-orders-api.md](backend-orders-api.md)) first makes the order's session unpayable (`POST /v1/checkout/sessions/{id}/expire` with `Stripe-Account`; a 400 is followed by a read of the session to tell `expired` from `complete`), then cancels the order. Only `pending` orders: a paid order is 409 (refunds are KAN-80). `complete` is 409 and Stripe failures are 502, in both cases the order stays `pending`.

## Data

Store migration `0008_order_checkout` (expand-only): `orders.shipping_minor` (default 0), `prices_include_tax` (default false), `stripe_checkout_session_id` (unique), `stripe_payment_intent_id`, `paid_at`, and the replaced total CHECK (the swap briefly locks `orders` while existing rows are checked). Store migration `0009_order_checkout_hardening` (KAN-256, expand-only): `orders.cart_id` (foreign key to `carts`, `ON DELETE SET NULL`), `checkout_fingerprint`, `stripe_checkout_url`, `checkout_expires_at`, the partial unique index above, a partial index on `cart_id` for the foreign key and a partial index for the sweep. Existing `pending` orders get `checkout_expires_at = created_at + 24 hours` (Stripe's default session life) so the sweep can never cancel an order whose session is still payable; their `cart_id` is null, so the unique index does not touch them. Downgrade drops the columns and indexes, no order is lost. Store databases are migrated by the existing store migration runner; no platform migration.

## Owner steps

1. **Before deploying this code**, run the store migrations to `0009` on every store database (the same runner as for `0007`). Otherwise checkout fails with a 500 on the new `orders` columns.
2. Vercel, FastAPI service: set `PLATFORM_ROOT_DOMAIN` to the same host as the frontend's (for example `storecart.com`; name only in tickets). Without it the store's own return URLs are refused (422).
3. Stripe Dashboard, Connect webhook endpoint (`/webhooks/stripe-connect`, events on **Connected accounts**): add `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.expired` and `checkout.session.async_payment_failed` (KAN-256).

## Known limits (not in this story)

- Stock is not reserved or decremented at payment, and the cart is not emptied after payment (KAN-77 or a follow-up).
- A first start whose Stripe outcome stayed unknown leaves a `pending` order with no session id. It is resumed for the same cart while at least 31 minutes remain; after that it is neither resumed, cancelled by the merchant nor replaced after a cart change (502) until it expires, because it may have a session at Stripe.
- **Delayed payment methods** (SEPA/ACH debit, bank transfer) are not requested: `payment_method_types` is not sent, so they are offered only if the merchant enabled them in their Stripe dashboard. Such a session completes unpaid and later fires `async_payment_succeeded`; the order stays `pending` meanwhile and the sweep leaves it alone (a completed session never answers `EXPIRED`).
- **Connected account changes.** The sweep, the merchant cancel and a replaced order read the organisation's *current* connected account. If it was reconnected to a different account after an order was created, Stripe answers 404 for the old session and 404 counts as expired, so that order can be cancelled while its session on the old account is still payable. Orders do not store their account id yet.
- **Rolling deploys.** An order written by code from before this change, after migration 0009 ran, has `cart_id`, `checkout_fingerprint` and `checkout_expires_at` NULL: it is not in the unique index and the sweep never selects it. Run the migration and deploy together, or accept those orders staying `pending` (the paid path still works for them).
- `store_orders.create_order` (flat tax rate, used by tests only) and `price_checkout_order` both build order lines from the catalogue; checkout uses only the second.
- The merchant order API does not return `shipping_minor` yet, so `subtotal + tax` can differ from `total` there.

## Tests

`tests/services/test_store_checkout.py` (fee, request, guard, service, no database), `tests/core/test_stripe_checkout.py` (form and headers), `tests/api/test_checkout.py` (route, no database), `tests/core/test_stripe_checkout_expiry.py` (`expires_at` and the expire call), `tests/services/test_store_checkout_expiry.py`, `tests/commands/test_sweep_checkout_orders.py`, `tests/api/test_checkout_fail_closed.py` (503 on a rate limiter outage), `tests/api/test_checkout_hardening_e2e.py` (real Postgres: a double start and concurrent double clicks give one order, a changed cart expires the old session first, the expired event cancels the order and is idempotent, the sweep, the merchant cancel expiring the session), `tests/services/test_store_checkout_hardening_schema_e2e.py` (migration 0009: existing rows, one pending order per cart, downgrade), `tests/api/test_checkout_e2e.py` (real Postgres: totals, client amounts refused, fee, charges guard, duplicate and concurrent confirmation, store rerun, livemode mismatch, unpaid then async success, amount mismatch, foreign session).
