# Stripe Connect onboarding (KAN-67)

**Last updated:** 2026-10-19

Each organisation owns one Stripe **Express** connected account. Merchants complete Stripe-hosted onboarding, a separate Connect webhook keeps the capability flags in sync, and checkout code must refuse to take payments until charges are enabled.

## API

Both routes sit under `/v1/organizations/{organization_id}/connect`, need the internal service key and a verified session, and are limited to an `OWNER` or `ADMIN` of the organisation (the same check as billing; a non-member sees 404, a `STAFF` member 403). Responses are `Cache-Control: no-store`.

| Route                              | Purpose                                                                                                                                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET  .../connect`                 | `{has_account, charges_enabled, payouts_enabled, details_submitted}`. The Stripe account id is never returned.                                                                                                            |
| `POST .../connect/onboarding-link` | Body `{return_url, refresh_url}`; both must be on `BILLING_RETURN_URL_ORIGINS` (422 otherwise). Creates the Express account on first use, then returns a one-time Stripe-hosted `url`. Optional `Idempotency-Key` header. |

Errors use the usual envelope with generic text: 403, 404, 422, 502 (Stripe failed), 503 (`STRIPE_SECRET_KEY` unset). No Stripe text, ids or account data reach a response or a log.

Account creation uses the deterministic Stripe idempotency key `sc-connect-account-{organization_id}` (honoured by Stripe for about 24 hours) and a conditional update (`link_account`), so two racing first requests end with one linked account.

## Webhook

`POST /webhooks/stripe-connect` (public, the signature is the credential, not in OpenAPI) handles only `account.updated`. It is a **separate endpoint with its own signing secret**, `STRIPE_CONNECT_WEBHOOK_SECRET` (a Connect endpoint's `whsec_...`, never the Billing one; startup fails if the two are equal). Verification is the shared `read_verified_body` (300 second tolerance, constant-time compare, 1 MB cap). Unset secret: 503.

- The update is one atomic `UPDATE ... WHERE stripe_connect_account_id = :id AND (stripe_connect_event_at IS NULL OR stripe_connect_event_at <= :created)`, so a redelivery rewrites the same values and a late, older event changes nothing. Stripe's `created` has one-second resolution, so two events in the same second apply in arrival order.
- An event for an unknown account, or any other event type, is acknowledged with 200 (nothing to retry). A signed but malformed `account.updated` is 400. Any other failure is a generic retryable 500.
- Known limits, left to KAN-69 (event routing and once-only processing): an `account.updated` that arrives before the account link is committed is acknowledged and dropped (the next event repairs it), and `account.application.deauthorized` is not handled.
- Vercel: `vercel.json` has a rewrite for the exact path, and `tests/core/test_vercel_routing.py` pins it.

## Checkout guard (acceptance criterion 3)

There is no checkout yet. The checkout story must call one of these before it creates any payment for an organisation's store:

```python
from app.services.stripe_connect import (
    ChargesNotEnabled,
    require_charges_enabled,
    require_org_charges_enabled,
)

await require_org_charges_enabled(OrgConnectRepository(session), organization_id)  # loads the organisation
require_charges_enabled(record)  # when you already hold the ConnectRecord
```

Both raise `ChargesNotEnabled` when the organisation has no connected account or charges are off (the async form also when the organisation is unknown). Map it to HTTP 409 with a generic message such as "Payments are not enabled for this store", and add a test at the checkout call site. `tests/services/test_stripe_connect.py` and `tests/api/test_org_connect_e2e.py` cover the guard itself.

## Owner steps (not in `.env.example`, which the coordinator owns)

1. Stripe Dashboard (test mode first): enable Connect for the platform account and add a webhook endpoint for **Connect** events (`account.updated`) pointing at `https://<app>/webhooks/stripe-connect`.
2. Vercel, FastAPI service: set `STRIPE_CONNECT_WEBHOOK_SECRET` to that endpoint's signing secret (name only in tickets and chat). Keep `STRIPE_SECRET_KEY` and `BILLING_RETURN_URL_ORIGINS` set; the app origin must be listed because the Connect return URLs use it.
3. Redeploy the backend. Local testing: `stripe listen --forward-connect-to localhost:8000/webhooks/stripe-connect`, then set `STRIPE_CONNECT_WEBHOOK_SECRET` to the secret it prints.

## Data

Migration `0010` adds to `organizations`: `stripe_connect_account_id` (unique), `connect_charges_enabled`, `connect_payouts_enabled`, `connect_details_submitted` (default false) and `stripe_connect_event_at`. The flags are written only by the webhook.

## Frontend

`src/lib/api/connect.ts` (server-only wrapper; the organisation is the caller's owner or admin organisation), `src/app/actions/connect-actions.ts` (curated messages, server-built return URLs `/dashboard/settings?connect=return|refresh`) and the **Payments** panel on the dashboard settings page (`connect-payments-panel.tsx`): status pills, Start or Continue onboarding, then a redirect to the Stripe-hosted link (https, `stripe.com` hosts only). Local e2e: `src/__tests__/e2e/connect-onboarding.spec.ts` (see [local-e2e.md](local-e2e.md)).
