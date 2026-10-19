# Stripe Connect onboarding and webhook (KAN-67, KAN-69)

**Last updated:** 2026-10-19

Each organisation owns one Stripe **Express** connected account. Merchants complete Stripe-hosted onboarding, a separate Connect webhook keeps the capability flags in sync, and checkout code must refuse to take payments until charges are enabled.

## API

Both routes sit under `/v1/organizations/{organization_id}/connect`, need the internal service key and a verified session, and are limited to an `OWNER` or `ADMIN` of the organisation (the same check as billing; a non-member sees 404, a `STAFF` member 403). Responses are `Cache-Control: no-store`.

| Route                              | Purpose                                                                                                                                                                                                                                                                             |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET  .../connect`                 | `{has_account, charges_enabled, payouts_enabled, details_submitted}`. The Stripe account id is never returned.                                                                                                                                                                      |
| `POST .../connect/onboarding-link` | Body `{return_url, refresh_url}`; both must be on `BILLING_RETURN_URL_ORIGINS` (422 otherwise). Creates the Express account on first use, then returns a one-time Stripe-hosted `url`. The Stripe link key is always server-generated (links are single use and expire in minutes). |

Errors use the usual envelope with generic text: 403, 404, 422, 502 (Stripe failed), 503 (`STRIPE_SECRET_KEY` unset). No Stripe text, ids or account data reach a response or a log.

Account creation uses the deterministic Stripe idempotency key `sc-connect-account-{organization_id}` (honoured by Stripe for about 24 hours) and a conditional update (`link_account`). Stripe answers 409 while a request with that key is in flight, so the losing request re-reads the organisation (using the account the winner linked) or retries once, and two racing first requests end with one linked account and two 200s. If the link step fails after the account was saved, the account stays linked and the next try reuses it.

## Webhook

`POST /webhooks/stripe-connect` (public, the signature is the credential, not in OpenAPI) handles `account.updated` and `account.application.deauthorized`. It is a **separate endpoint with its own signing secret**, `STRIPE_CONNECT_WEBHOOK_SECRET` (a Connect endpoint's `whsec_...`, never the Billing one; startup fails if the two are equal, and logs a warning in production when `STRIPE_SECRET_KEY` is set but this secret is not). Verification is the shared `read_verified_body` (`app/core/stripe_webhook_body.py`: 300 second tolerance, constant-time compare, 1 MB cap). Unset secret: 503.

- **The event is only a trigger.** Stripe delivers events unordered and `created` has one-second resolution, so the flags are never read from the payload. `account.updated` retrieves the account (`GET /v1/accounts/{id}`) and stores what Stripe reports now. Each write is one atomic `UPDATE ... WHERE stripe_connect_account_id = :id AND (stripe_connect_event_at IS NULL OR stripe_connect_event_at <= :read_started_at)`, so a slower, older read that finishes later cannot overwrite a newer one (the column holds the time the read started, microsecond resolution), and a redelivery rewrites the same values.
- `account.application.deauthorized` (the connected account is the event's top-level `account`) clears all three flags. An account Stripe no longer knows is treated the same.
- An event for an unknown account, or any other event type, is acknowledged with 200 (nothing to retry). A signed event without an account id is 400. A Stripe outage or any other failure is a generic retryable 500; an unset `STRIPE_SECRET_KEY` is a retryable 503.
- Known limit: Stripe can send `account.updated` right after the account is created, before `link_account` commits. That event finds no organisation, is acknowledged and not recorded, so it is lost; the flags catch up on the account's next event (onboarding progress always produces more). Returning 5xx for unknown accounts instead would make Stripe retry events of unrelated accounts for days.
- Vercel: `vercel.json` has a rewrite for the exact path, and `tests/core/test_vercel_routing.py` pins it.

### Routing and once-only processing (KAN-69)

`ConnectWebhookService` (`app/services/stripe_connect.py`) processes every handled event in this order:

1. **Type.** Account events (`account.updated`, `account.application.deauthorized`) and the store-scoped types registered in `store_handlers` are handled. Any other type is acknowledged (200), logged by type only, and not recorded. A handled event needs an `evt_...` id, a positive `created` time and an `acct_...` account, else 400.
2. **Route.** The connected account (the event's top-level `account`, which Stripe sets; for `account.updated` also its object id, and the two must agree) picks the organisation through the unique `organizations.stripe_connect_account_id`. Store-scoped events must also carry `metadata.store_id` on their object, naming a store of **that** organisation. An unknown account, a missing store id, or a store of another organisation is acknowledged with 200, logged without ids from the payload, and not recorded, so Stripe does not retry it forever.
3. **Once only.** A pre-check skips an event already in `stripe_connect_events` before any Stripe call. Any Stripe read (`account.updated`) happens outside a transaction. Then, in one transaction, the event id is claimed (`INSERT ... ON CONFLICT (stripe_event_id) DO NOTHING RETURNING id`), the side effect runs and both commit. A concurrent delivery of the same id waits on the unique index and gets a duplicate (200, nothing applied); a failing handler rolls back the claim too, so Stripe's retry runs it again.

Adding a payment event (KAN-68 checkout, KAN-80 refunds): write an async handler `(route: ConnectRoute, obj: Mapping[str, Any]) -> None`. It runs inside the platform transaction that holds the claim, so it must **not commit or roll back**, must be **short** (concurrent redeliveries wait on the claim's lock, each holding a pooled connection), and must be **idempotent** for any write outside that transaction (a store database opened with `get_store_session(route.store_id)`): a failure after such a write rolls back only the claim, and Stripe's retry runs the handler again. Register it in `get_connect_webhook_service` (`app/api/v1/webhooks_connect.py`) under its event type, and put `metadata[store_id]` on the Stripe object you create (Checkout Session and PaymentIntent metadata). Add the type to the Connect endpoint in the Stripe Dashboard. Do not trust `metadata` for anything except picking the store: the route has already checked the store belongs to the account's organisation.

Billing (`POST /webhooks/stripe`, `STRIPE_WEBHOOK_SECRET`, ledger `stripe_events`) is unchanged and fully separate: neither secret verifies the other endpoint's events.

## Checkout guard (acceptance criterion 3)

There is no checkout yet: this PR only provides the guard as a function. The checkout story (KAN-68) must call one of these before it creates any payment for an organisation's store:

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

1. Stripe Dashboard (test mode first): enable Connect for the platform account and add a webhook endpoint that listens to events on **Connected accounts** (not "Your account") pointing at `https://<app>/webhooks/stripe-connect`, with `account.updated` and `account.application.deauthorized` (payment stories add their own types). This endpoint has its own signing secret; the Billing endpoint (`/webhooks/stripe`, events on your account) keeps `STRIPE_WEBHOOK_SECRET`.
2. Vercel, FastAPI service: set `STRIPE_CONNECT_WEBHOOK_SECRET` to that endpoint's signing secret (name only in tickets and chat). Keep `STRIPE_SECRET_KEY` and `BILLING_RETURN_URL_ORIGINS` set; the app origin must be listed because the Connect return URLs use it.
3. Redeploy the backend. Local testing: `stripe listen --forward-connect-to localhost:8000/webhooks/stripe-connect`, then set `STRIPE_CONNECT_WEBHOOK_SECRET` to the secret it prints.

## Data

Migration `0010` adds to `organizations`: `stripe_connect_account_id` (unique), `connect_charges_enabled`, `connect_payouts_enabled`, `connect_details_submitted` (default false) and `stripe_connect_event_at`. The flags are written only by the webhook.

Migration `0011` (KAN-69) adds `stripe_connect_events`: `stripe_event_id` (unique, the idempotency key), `type`, `stripe_account_id`, `organization_id` (cascade with the organisation), `store_id` (nullable, set null when the store is deleted), `stripe_created_at`, `created_at`. A row means processed, including a no-op (for example a newer read was already stored). No payload is stored. The ledger is append-only; a retention job can be added later if it grows.

## Frontend

`src/lib/api/connect.ts` (server-only wrapper; the organisation is the one that owns the dashboard's selected store, validated by `getCurrentStoreSelection()`, so a user with several organisations sets up payments for the one they are looking at), `src/app/actions/connect-actions.ts` (curated messages, server-built return URLs `/dashboard/settings?connect=return|refresh`) and the **Payments** panel on the dashboard settings page (`connect-payments-panel.tsx`): status pills, Start or Continue onboarding, a Refresh status button after returning from Stripe (the `?connect=` marker is stripped from the address bar), then a redirect to the Stripe-hosted link (https, `stripe.com` hosts only). Users with no organisation or without the owner/admin role see a plain note without Retry. Local e2e: `src/__tests__/e2e/connect-onboarding.spec.ts` (see [local-e2e.md](local-e2e.md)).
