# Storefront checkout on the merchant's connected account (KAN-68)

**Last updated:** 2026-10-19

A shopper's cart becomes a `pending` order priced only on the server, and a Stripe Checkout Session created as a **direct charge** on the store organisation's connected account (KAN-67). The Connect webhook (KAN-69) marks the order `paid`. The storefront UI that calls this is KAN-77.

## API

`POST /v1/storefront/{slug}/checkout` (internal service key, no user session, `CHECKOUT_POLICY` 10/min per client IP, `Cache-Control: no-store`). The cart token travels in `X-Cart-Token`, like the cart routes ([backend-storefront-cart.md](backend-storefront-cart.md)).

| Body | Rule |
|---|---|
| `success_url`, `cancel_url` | Required. The origin must be on `BILLING_RETURN_URL_ORIGINS`, or be the store's own subdomain of one of those origins (`https://www.example.com` also allows `https://{slug}.example.com`; a leading `www.` is dropped). Anything else is 422. |
| anything else | 422. The client can never send an amount, a price or a line. |

Answer: `{order_id, checkout_url}`; redirect the shopper to `checkout_url` (Stripe-hosted). Errors (generic text, no Stripe output): 404 store not found (unknown, not ACTIVE), 409 "Payments are not enabled for this store" (no connected account or charges off; nothing is written), 409 cart empty or changed (a line unavailable, out of stock or above stock), 422 return URL, 502 Stripe failed (the order is cancelled), 503 `STRIPE_SECRET_KEY` unset or store database unavailable.

## How the amounts are made

1. The cart must be checkout-ready (`can_checkout`).
2. `price_checkout_order` (`app/services/store_checkout.py`) re-reads each variant from the catalogue under `FOR SHARE` and prices it with `compute_totals` and the store settings (KAN-82/83): subtotal, shipping, tax (added on top, or included in prices) in integer minor units. The order stores `shipping_minor` and `prices_include_tax`, and the database checks `total = subtotal + shipping + (tax unless included)`.
3. The session's line items are the order lines, then a `Tax` line (only when tax is added on top) and a `Shipping` line; their sum must equal the order total or nothing is sent. Currency is the platform currency setting.

## Stripe call

`POST /v1/checkout/sessions` with `Stripe-Account: acct_...` (direct charge: the merchant is the merchant of record; the payment, Stripe's fees, disputes and refunds are on their account), `mode=payment`, `metadata[store_id]`, `metadata[order_id]` (also on the PaymentIntent), `client_reference_id` = order id. Idempotency key `sc-checkout-{store_id}-{order_id}`, built on the server, so a retried call cannot create a second session for one order.

**Platform fee.** `payment_intent_data[application_fee_amount]` = `round_half_up(total * organizations.platform_fee_bps / 10000)`. `platform_fee_bps` defaults to 0 (decision D9: subscription revenue only), and then the field is **not sent**. Raising the column for an organisation turns the fee on with no code change. The fee code is `platform_fee_minor`.

## Confirmation (Connect webhook)

Registered store handlers: `checkout.session.completed` and `checkout.session.async_payment_succeeded` (`checkout_payment_handler`, wired in `app/api/v1/webhooks_connect.py`). KAN-69 has already checked the signature, the mode (`livemode` must match the platform key, otherwise ignored), the event id (once only) and that `metadata.store_id` is a store of the account's organisation.

- Only `payment_status = paid` moves anything; `completed` with `unpaid` (a delayed payment method) waits for `async_payment_succeeded`.
- `mark_checkout_paid` is one conditional `UPDATE`: the order (from `metadata.order_id`) must be `pending`, linked to this session or none yet, and `amount_total`/`currency` must equal its total and currency. A session already linked to another order never pays this one (`stripe_checkout_session_id` is unique).
- `metadata.order_id` picks the order (KAN-69's rule is to trust metadata only to pick the store). That is safe here because only the platform can create sessions on an Express account (the merchant has no API keys), and the update still requires the order's own amount, currency and session, so a forged id cannot pay a different order.
- Store-database writes are at least once (KAN-69): a rerun or a concurrent delivery finds the order paid and changes nothing. Mismatches (amount, currency, another session, a cancelled order) are logged as errors and acknowledged; a paid session for a cancelled order needs a manual refund in the merchant's dashboard.

## Data

Store migration `0008_order_checkout` (expand-only): `orders.shipping_minor` (default 0), `prices_include_tax` (default false), `stripe_checkout_session_id` (unique), `stripe_payment_intent_id`, `paid_at`, and the new total CHECK (added `NOT VALID`, then validated). Store databases are migrated by the existing store migration runner; no platform migration.

## Owner steps

1. Stripe Dashboard, Connect webhook endpoint (`/webhooks/stripe-connect`, events on **Connected accounts**): add `checkout.session.completed` and `checkout.session.async_payment_succeeded`.
2. Run the store migrations to `0008` on every store database (the same runner as for `0007`).

## Known limits (not in this story)

- Stock is not reserved or decremented at payment, and the cart is not emptied after payment (KAN-77 or a follow-up).
- Every call creates a new order: a double click makes two pending orders, and only the paid one becomes `paid`. Unpaid pending orders are not expired yet.
- The merchant order API does not return `shipping_minor` yet, so `subtotal + tax` can differ from `total` there.

## Tests

`tests/services/test_store_checkout.py` (fee, request, guard, service, no database), `tests/core/test_stripe_checkout.py` (form and headers), `tests/api/test_checkout.py` (route, no database), `tests/api/test_checkout_e2e.py` (real Postgres: totals, client amounts refused, fee, charges guard, duplicate and concurrent confirmation, store rerun, livemode mismatch, unpaid then async success, amount mismatch, foreign session).
