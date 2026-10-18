# Backend: organisation billing endpoints (KAN-43)

Authenticated routes in `fastapi_backend` that let an organisation's owners and admins start and manage the
Stripe Billing subscription ([ADR-010](../adr/0010-accounts-and-payments-model.md)). The Stripe webhook
([backend-billing-webhook.md](./backend-billing-webhook.md), KAN-44) remains the **only writer of subscription
state** (tier, status, price, period). These routes only ask Stripe to act; the one value they save is the
organisation's `stripe_customer_id`, before the first Checkout, so the webhook can find the organisation.

## Routes

All under `/v1/organizations/{organization_id}/billing`. Every route needs `X-Internal-Key`, a verified session
(`X-Session-Token`, verified email) and is rate limited by subject (`API_POLICY`). Responses use the usual
`{"success": true, "data": ...}` envelope with `Cache-Control: no-store`.

| Method and path                         | Purpose                                                                                                            | Success                          |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------- |
| `GET  /`                                | Plan (limits from `app/core/plans.py`), subscription status, period end, flags, `cancel_at_period_end`, `interval` | `plan`, `subscription_status`... |
| `POST /checkout`                        | Stripe Checkout session for `plan` (`pro`/`enterprise`) and `interval`                                             | `{url}`                          |
| `POST /portal`                          | Stripe customer-portal session                                                                                     | `{url}`                          |
| `POST /plan`                            | Swap the price on the live subscription (prorated)                                                                 | `{success: true}`                |
| `POST /cancel`                          | Cancel at period end                                                                                               | `{success: true}`                |
| `POST /resume`                          | Undo a pending cancellation                                                                                        | `{success: true}`                |
| `GET  /invoices`                        | Latest 12 invoices (id, number, status, amounts, currency, hosted/PDF links)                                       | list                             |
| `GET  /payment-methods`                 | Saved cards (brand, last4, expiry, `is_default`)                                                                   | list                             |
| `DELETE /payment-methods/{pm_id}`       | Detach a saved card (KAN-182)                                                                                      | `{success: true}`                |
| `POST /payment-methods/{pm_id}/default` | Make a saved card the customer's default (KAN-182)                                                                 | `{success: true}`                |

Checkout and portal bodies carry `success_url`/`cancel_url` and `return_url`. Optional `Idempotency-Key` header
(8 to 64 characters of `A-Za-z0-9_-`) lets a client make a retry replay-safe; without it the server generates one.

## Renewal state, interval and cards (KAN-182)

- **`cancel_at_period_end`** (`GET /`) is the stored column `organizations.stripe_cancel_at_period_end` (migration
  `0004`). The webhook is still the only writer: `parse_subscription` reads Stripe's `cancel_at_period_end`, falling
  back to a scheduled `cancel_at`, and `plan_change` stores it under the existing ordering and tie rules. An ended
  subscription (or a `deleted` event) stores `false`. `/cancel` and `/resume` do not write it; the flag changes when
  Stripe's `customer.subscription.updated` event arrives.
- **`interval`** (`monthly`, `yearly` or `null`) is derived on every read by looking `stripe_price_id` up in
  `price_catalogue()` (the `STRIPE_PRICE_ID_*` settings). It is `null` when the price is unmapped. **If a price id is
  rotated in settings, subscriptions still on the old price read `null` until their price changes**; keep old ids
  configured, or accept `null`, during a rotation. The tier is unaffected.
- **`is_default`** (`GET /payment-methods`) is read live from the Stripe customer's
  `invoice_settings.default_payment_method`; nothing is stored. An extra Stripe call is made per list.
- **`DELETE /payment-methods/{pm_id}`** and **`POST /payment-methods/{pm_id}/default`**: OWNER or ADMIN only, and the
  `Idempotency-Key` header is **required** (missing or malformed: 422, before any Stripe call). `pm_id` must look like
  `pm_...`. Ownership is checked against Stripe: the payment method's customer must equal the organisation's
  `stripe_customer_id`. A payment method that is unknown, belongs to another customer, or an organisation with no
  customer all return the same **404** `Payment method not found` (byte-identical), so an admin cannot detach or probe
  another customer's card. Deleting the **default** card while the subscription is live (any status that still has a
  subscription, as for checkout) returns **409**, because it would make renewal fail; set another default first or
  use the portal. Stripe failures are the usual generic 502.

### Backfill for organisations subscribed before migration `0004`

The migration cannot call Stripe, so the column is added `NOT NULL DEFAULT false` and existing rows read `false`. An
organisation that had already scheduled cancellation shows "will renew" until Stripe sends its next
`customer.subscription.updated` event (any subscription change, including the one Stripe sends at renewal). To
correct them sooner, once per environment after the migration, either: in the Stripe dashboard resend the latest
`customer.subscription.updated` event for each subscription that is set to cancel (an event with the same `created`
second as the stored one is applied, an older one is ignored), or touch the subscription in Stripe (for example
update its metadata) to emit a new event. Find the affected rows with
`SELECT id FROM organizations WHERE stripe_subscription_id IS NOT NULL` and check each in Stripe. New and changed
subscriptions are always correct because the webhook stores the flag.

## Authorisation

`OrgBillingService.authorize` runs first in every method:

- Not a member of the organisation (or no such organisation): **404** `Organization not found`, so one
  organisation cannot learn another exists.
- A member with role `STAFF`: **403** `Forbidden`. Only `OWNER` and `ADMIN` manage billing, **including reading**
  invoices, cards and plan state.
- The organisation is always taken from the path and checked against the caller's membership; no Stripe id is
  ever accepted from the client (the subscription and customer come from the database).

The merchant authorisation dependency planned as KAN-52 does not exist yet, so this uses the verified identity
(`CurrentUserIdDep`) plus the `memberships` table. When KAN-52 lands, replace `authorize`'s membership lookup with it.

## Rules and errors

| Status | When                                                                                                                                                                                                                                                             |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 409    | Checkout while a subscription is live (any status except `canceled`/`incomplete_expired`, including `unpaid`, `incomplete`, `paused`: use the portal); plan change, cancel, resume without one; portal without a customer; same-price plan change; the free plan |
| 422    | Return URL not on the allow-list, malformed body or `Idempotency-Key`                                                                                                                                                                                            |
| 502    | Any Stripe failure. The body is always `Billing provider unavailable`                                                                                                                                                                                            |
| 503    | `STRIPE_SECRET_KEY` empty or unset, or the requested `STRIPE_PRICE_ID_*` not set                                                                                                                                                                                 |

**Return URLs** must be `http(s)`, without credentials, whitespace or backslashes, and their origin
(`scheme://host[:port]`) must be in `BILLING_RETURN_URL_ORIGINS`. An empty setting rejects every URL.

**Idempotency.** Every Stripe create or update call carries an `Idempotency-Key`: `sc-<operation>-<org id>-<client
key or generated id>`. The customer key is deterministic per organisation (`sc-customer-<org id>`), and the saved
id is set with `UPDATE ... WHERE stripe_customer_id IS NULL`, so concurrent first checkouts end with one customer.

**No leakage.** `app/core/stripe_billing.py` turns every failure into a `StripeError` with no Stripe text. It logs
only a status code or exception type, and sets the `httpx` logger to WARNING (its INFO lines include query
strings such as `?customer=cus_...`). Responses never include Stripe ids.

## Stripe client

`StripeBilling` (Protocol, `app/core/stripe_billing.py`) is the seam. `HttpStripeBilling` calls the Stripe REST API
with httpx (10 second timeout, form encoded, Bearer secret key); `get_stripe_billing()` builds it from settings and
tests override the `stripe_billing` dependency with `tests/fakes_billing.py:FakeStripe`. `httpx` is now a direct
dependency (it was already installed through `fastapi[standard]`).

## Configuration

| Variable                     | Meaning                                                                                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `STRIPE_SECRET_KEY`          | Stripe secret API key (`SecretStr`). Unset: the routes answer 503. Server-only.                                                         |
| `BILLING_RETURN_URL_ORIGINS` | Comma separated origins allowed as Checkout/portal return targets, e.g. `https://app.example.com`. Unset: every return URL is rejected. |

The existing `STRIPE_PRICE_ID_{PRO,ENTERPRISE}_{MONTHLY,YEARLY}` settings choose the price. Add both new variables
to `.env.example` and Vercel (the coordinator owns `.env.example`).

## Checkout troubleshooting (KAN-250)

The pricing page's Upgrade button used to show one alert for every failure. It now shows an inline message chosen
from the cause, and the cause is logged. Match the log line to the setting to fix:

| Frontend log (`Create checkout session failed:`) | Backend log (`org billing request failed:`) | What to check (names only) |
| --- | --- | --- |
| `code: no_organization` | none (the frontend never calls billing) | The user has no organisation: it is created during onboarding, so create a store first |
| `code: return_url_config` | none | Frontend `NEXT_PUBLIC_APP_URL` (required in production, a full `https://` URL, set at build time) |
| `code: invalid_return_url`, `status: 422` | `cause=InvalidReturnUrl status=422` | Backend `BILLING_RETURN_URL_ORIGINS` must contain the app origin, e.g. `https://store-cart-nextjs.vercel.app`, with no path and no trailing slash |
| `code: not_configured`, `status: 503` | `cause=BillingNotConfigured status=503`, or no line when `STRIPE_SECRET_KEY` is unset | Backend `STRIPE_SECRET_KEY` and the `STRIPE_PRICE_ID_PRO_MONTHLY` / `STRIPE_PRICE_ID_PRO_YEARLY` (Enterprise: `_ENTERPRISE_MONTHLY` / `_ENTERPRISE_YEARLY`) names |
| `code: provider_unavailable`, `status: 502` | `billing stripe call failed: <class>` and `stripe call failed: status=... type=... code=...` | Stripe rejected the call: `resource_missing` is a price id that does not exist in the account the key belongs to (test vs live mix-up) |
| `code: backend_unavailable` | none | Frontend `BACKEND_API_URL`, `BACKEND_INTERNAL_KEY` (must equal the backend's) |
| `code: forbidden` / `not_allowed` | `cause=BillingForbidden` / `BillingConflict` | Caller is not OWNER or ADMIN, or the organisation already has a live subscription |

The price ids are backend settings: the pricing page asks the backend for the plan, and only the backend reads
`STRIPE_PRICE_ID_*` for checkout. Logs carry the exception class, the HTTP status and Stripe's own enum `type` and
`code` only; never Stripe text, ids, URLs or keys.

## Tests

- `tests/services/test_org_billing.py`, `tests/core/test_stripe_billing.py`, `tests/api/test_org_billing.py`: fakes,
  no network, no database.
- `tests/api/test_org_billing_e2e.py`: the real app, dependency chain and Postgres (same `TEST_DATABASE_URL` contract
  as the webhook end-to-end test) with a fake Stripe client: 401, unverified email, cross-organisation 404, STAFF 403,
  OWNER and ADMIN happy paths, customer linking and concurrency, invalid return URL, Stripe failure, and a signed
  webhook upgrading the organisation after checkout. KAN-182 adds the webhook-stored flag (set, cleared, `cancel_at`,
  stale event), `interval` (including an unmapped price), `is_default`, and delete and set-default (ownership 404
  identical to unknown, 409 on the default card, STAFF 403, missing key 422).

## Not verified here

No call was made to the real Stripe API: the request shapes in `HttpStripeBilling` follow Stripe's documented REST
API but are tested only against a mock transport. Smoke-test checkout, the portal and a plan change in Stripe test
mode before release (KAN-157 covers test-mode webhook routing).

## Known limits (follow-ups, not in this ticket)

- The webhook lags Checkout, so two checkouts started before it lands can create two Stripe subscriptions; the
  stored-status guard cannot see them. A Stripe-side "list active subscriptions" check or a stricter billing-write
  rate limit would close it.
- Without an `Idempotency-Key` header a client retry is a new Stripe operation; send the header from the UI.
- No `Stripe-Version` header is sent, so response shapes follow the account's API version.
