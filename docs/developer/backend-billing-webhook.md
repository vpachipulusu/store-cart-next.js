# Backend: Stripe Billing webhook (KAN-44)

`POST /webhooks/stripe` in `fastapi_backend` keeps an organisation's subscription in sync with Stripe Billing
([ADR-010](../adr/0010-accounts-and-payments-model.md)). It is the only Stripe webhook: the legacy Next.js route
(`/api/webhooks/stripe`) was removed in KAN-50.

## Request handling

1. **Public route.** No `X-Internal-Key` ([ADR-003](../adr/0003-nextjs-to-fastapi-authentication.md) section 5); the
   Stripe signature is the credential. The route is left out of the OpenAPI schema.
2. **Signature on the raw body** (`app/core/stripe_signature.py`): HMAC-SHA256 of `"{t}.{raw bytes}"` with
   `STRIPE_WEBHOOK_SECRET`, compared in constant time, 300 second timestamp tolerance, any matching `v1` accepted.
   A bad, missing or stale signature returns **400** and nothing is processed. If the secret is not configured the
   route returns **503**. Bodies over 1 MB return 413 (checked while streaming).
3. **Event types.** `customer.subscription.created`, `.updated` and `.deleted` are handled. Any other type is
   acknowledged with 200 and ignored (no row written).
4. **Responses.** 200 `{"received": true}` for processed, duplicate, ignored and unmatched events; 400 for a
   signed but malformed payload; a generic **500** when the handler fails, so Stripe retries. No payload,
   header or secret is logged; failures log the exception type only.
5. There is no rate limit on this route: limiting before the signature check would let anyone throttle real
   Stripe deliveries, and the check is cheap.

## Idempotency and transactions

`stripe_events` has a unique `stripe_event_id`. The service inserts it with `INSERT ... ON CONFLICT DO NOTHING`
**in the same transaction** as the organisation update and commits once. A handler that fails rolls both back, so
the event is not marked processed and the retry runs again. A concurrent delivery of the same id blocks on the
unique index until the first transaction ends, then sees a duplicate (or inserts, if the first rolled back).
The organisation row is locked (`SELECT ... FOR UPDATE`) while it is updated.

## Out-of-order events

`organizations.stripe_subscription_event_at` stores the Stripe `created` time of the last event applied. An event
with an older `created` is recorded but does not change the organisation. Also, an ending event (`deleted`, or a
`canceled`, `unpaid`, `incomplete_expired`, `paused` status) for a subscription that is not the organisation's
current one is ignored, and so is a non-paying (for example `incomplete`) event for a different subscription, so
neither can downgrade or hide the current one. Stripe times have one second resolution: in the same second, an
ended state is final and a `created` event does not overwrite an update.

## State mapping

The organisation is found by `stripe_subscription_id`, else by `stripe_customer_id` (KAN-43 stores the customer
before checkout). An event that matches no organisation is acknowledged (200) with a warning carrying the event id, but **not
recorded**, so a redelivery is processed once the organisation is linked. KAN-43 must save the customer id before
sending the user to Checkout; a failed link is otherwise only healed by the next event for that subscription.

| Stripe status                                        | `subscription_status` | `subscription_tier`                                   |
| ---------------------------------------------------- | --------------------- | ----------------------------------------------------- |
| `active`, `trialing`, `past_due`                     | as sent               | from the price id (unmapped price: unchanged, warned) |
| `canceled`, `unpaid`, `incomplete_expired`, `paused` | as sent               | `free`, price cleared                                 |
| `incomplete` and anything else                       | as sent               | unchanged                                             |
| `customer.subscription.deleted`                      | `canceled`            | `free`, price cleared                                 |

`stripe_current_period_end` is read from the subscription, or from its first item in newer API versions.

## Configuration

`STRIPE_WEBHOOK_SECRET` (the Billing endpoint's `whsec_...`; a separate endpoint and secret from Connect, ADR-010)
and the price ids `STRIPE_PRICE_ID_{PRO,ENTERPRISE}_{MONTHLY,YEARLY}` map prices to plans (`app/core/plans.py`).
All are optional in settings; they must be set on Vercel for the webhook to work. Add them to `.env.example`.

## Schema

Migration `0002`: table `stripe_events` (`id`, `stripe_event_id` unique, `type`, `stripe_created_at`,
`created_at`; no payload) and column `organizations.stripe_subscription_event_at`. Rows in `stripe_events` can be
pruned after 30 days; Stripe stops retrying after 3 days.

## Tests

- `tests/core/test_stripe_signature.py`, `tests/services/test_stripe_webhook.py` and
  `tests/api/test_stripe_webhook_route.py` run with fakes and no database.
- `tests/api/test_stripe_webhook_e2e.py` posts signed payloads through the real ASGI app against Postgres: valid,
  replayed, concurrent, bad signature, unknown type, out of order, failed-then-retried, unknown customer. It runs only
  when `TEST_DATABASE_URL` is set and **rebuilds that database with Alembic (downgrade base, upgrade head)**; the
  name must end in `_test` and the host must be local. CI sets it for the backend job (Postgres 17 service `storecart_test`). Locally:
  `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/storecart_test uv run pytest tests/api/test_stripe_webhook_e2e.py`.

## Production checklist (KAN-251)

After paying, the owner returns to `/dashboard?upgrade=success` but the plan stays Free when Stripe events never reach
this route. Check, in this order:

1. **Routing.** The backend service has no public route (ADR-011), so Stripe reaches it only through the top-level
   rewrite `/webhooks/stripe` to `fastapi_backend` in the root `vercel.json`, placed before the catch-all. Without it
   the event goes to the frontend (404) and no subscription state is ever written. The rewrite is exact (no wildcard)
   and public: no `X-Internal-Key`, the Stripe signature is the credential (ADR-003 section 5).
   `tests/core/test_vercel_routing.py` guards it.
2. **Variable** (Vercel project, FastAPI service, Production scope; name only): `STRIPE_WEBHOOK_SECRET`, the `whsec_...`
   signing secret of the endpoint in step 3. If unset, the route answers **503** and Stripe keeps retrying. The price
   ids `STRIPE_PRICE_ID_{PRO,ENTERPRISE}_{MONTHLY,YEARLY}` must also be set, or the tier stays unchanged (warned).
   **Not the `stripe listen` secret.** The secret that `stripe listen` prints (and that local e2e keeps in
   `.env.e2e.local`) belongs to the local forwarder only. Stripe signs real deliveries with the endpoint's own
   secret, so production configured with the CLI secret answers **400** to every event and the plan never changes
   (KAN-251: found because every event stayed `pending_webhooks=1` while a harmless probe signed with the CLI
   secret was accepted).
   Never paste a `whsec_` value into tickets, chat or logs.
3. **Stripe dashboard** (Developers, Webhooks, add endpoint; use the live or test mode that matches the keys in
   use): URL `https://<production origin>/webhooks/stripe` (no trailing slash), events `customer.subscription.created`,
   `customer.subscription.updated` and `customer.subscription.deleted`. These are the only types the backend acts on;
   others (for example `checkout.session.completed`) are acknowledged and ignored. Copy the endpoint's signing secret
   into `STRIPE_WEBHOOK_SECRET` (step 2) and redeploy.
4. **Deployment Protection.** Stripe sends no Vercel bypass header. If the production domain is behind Vercel
   Authentication or a password, add a protection-bypass exception for `/webhooks/stripe` only.

### How to verify

- Stripe CLI (read-only): `stripe events list --type customer.subscription.created` shows `pending_webhooks`; `1` means the endpoint has not returned 2xx yet. After fixing the secret, resend with `stripe events resend <evt_id> --webhook-endpoint=<we_id>` (or the dashboard's Resend): the plan then flips without a new payment.
- After checkout the dashboard polls for about 30 seconds. If the plan has not flipped it keeps a "Payment received" banner (it no longer disappears) telling the user to contact support if the plan still shows Free later.

- In the Stripe dashboard the endpoint's recent deliveries show **200** (`{"received": true}`).
- Run a test checkout: the organisation's plan flips from Free to Pro on the billing page after the redirect.

| Stripe delivery shows | Meaning |
|---|---|
| 404 | Routing (item 1) not deployed, or the endpoint URL is on another domain |
| 503 | `STRIPE_WEBHOOK_SECRET` is unset on the FastAPI service |
| 400 | Wrong secret: most often the `stripe listen` / `.env.e2e.local` secret instead of this endpoint's, or an endpoint from the other mode, or a rotated one. The backend log says `stripe webhook signature rejected: header=present` (or `missing`) |
| 401 with an HTML sign-in page | Deployment Protection (item 4) |
| 413 | Body over 1 MB (not a real Stripe event) |
| 500 | Handler failed; Stripe retries for up to 3 days, check the backend logs (exception type only) |
| 200 but plan unchanged | Event type ignored (`stripe event ignored: type=...`), price id unmapped (`price not mapped to a plan`), or no organisation matches the customer (`matches no organisation`, with the event id) |

## Follow-ups outside this ticket

- `.env.example` and `getting-started.md` entries for the new variables.
