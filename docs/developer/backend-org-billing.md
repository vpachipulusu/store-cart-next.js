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

| Method and path         | Purpose                                                                        | Success                          |
| ----------------------- | ------------------------------------------------------------------------------ | -------------------------------- |
| `GET  /`                | Plan (limits from `app/core/plans.py`), subscription status, period end, flags | `plan`, `subscription_status`... |
| `POST /checkout`        | Stripe Checkout session for `plan` (`pro`/`enterprise`) and `interval`         | `{url}`                          |
| `POST /portal`          | Stripe customer-portal session                                                 | `{url}`                          |
| `POST /plan`            | Swap the price on the live subscription (prorated)                             | `{success: true}`                |
| `POST /cancel`          | Cancel at period end                                                           | `{success: true}`                |
| `POST /resume`          | Undo a pending cancellation                                                    | `{success: true}`                |
| `GET  /invoices`        | Latest 12 invoices (id, number, status, amounts, currency, hosted/PDF links)   | list                             |
| `GET  /payment-methods` | Saved cards (brand, last4, expiry only)                                        | list                             |

Checkout and portal bodies carry `success_url`/`cancel_url` and `return_url`. Optional `Idempotency-Key` header
(8 to 64 characters of `A-Za-z0-9_-`) lets a client make a retry replay-safe; without it the server generates one.

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

| Status | When                                                                                                                                                                                  |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 409    | Checkout while a subscription is live (any status except `canceled`/`incomplete_expired`, including `unpaid`, `incomplete`, `paused`: use the portal); plan change, cancel, resume without one; portal without a customer; same-price plan change; the free plan |
| 422    | Return URL not on the allow-list, malformed body or `Idempotency-Key`                                                                                                                 |
| 502    | Any Stripe failure. The body is always `Billing provider unavailable`                                                                                     |
| 503    | `STRIPE_SECRET_KEY` empty or unset, or the requested `STRIPE_PRICE_ID_*` not set                                                                                                                                                         |

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

## Tests

- `tests/services/test_org_billing.py`, `tests/core/test_stripe_billing.py`, `tests/api/test_org_billing.py`: fakes,
  no network, no database.
- `tests/api/test_org_billing_e2e.py`: the real app, dependency chain and Postgres (same `TEST_DATABASE_URL` contract
  as the webhook end-to-end test) with a fake Stripe client: 401, unverified email, cross-organisation 404, STAFF 403,
  OWNER and ADMIN happy paths, customer linking and concurrency, invalid return URL, Stripe failure, and a signed
  webhook upgrading the organisation after checkout.

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
