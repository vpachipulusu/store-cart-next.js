# Backend: admin subscriptions API (KAN-48)

Platform-admin routes in `fastapi_backend` to list organisation subscriptions, view one, cancel it, refund a
payment and grant a complimentary plan. Revenue analytics and bulk Stripe sync are out of scope (KAN-114).
Subscription state belongs to the **organisation**; the Stripe webhook
([backend-billing-webhook.md](./backend-billing-webhook.md)) stays the **only writer** of tier, status, price and
period. These routes ask Stripe to act and return; the webhook records the outcome.

## Routes

All under `/v1/admin/subscriptions`. Every route needs `X-Internal-Key`, a verified session and a platform admin
record holding the permission below (`require_admin`: 401 without a session, 403 with one generic body for a
non-admin, a merchant, or a missing permission). Responses use `{"success": true, "data": ...}` and
`Cache-Control: no-store`. Rate limited by subject (`API_POLICY`).

| Method and path                   | Permission             | Purpose                                                                    |
| --------------------------------- | ---------------------- | -------------------------------------------------------------------------- |
| `GET  /`                          | `subscriptions.read`   | Page: filters `status`, `plan`; `limit` 1-100 (default 20), `offset`        |
| `GET  /{organization_id}`         | `subscriptions.read`   | One organisation: plan, status, period, grant, Stripe ids, recent payments |
| `POST /{organization_id}/cancel`  | `subscriptions.update` | Cancel at period end (default) or immediately                              |
| `POST /{organization_id}/refunds` | `subscriptions.refund` | Refund a charge, fully or partly                                           |
| `PUT  /{organization_id}/grant`   | `subscriptions.grant`  | Complimentary `pro` or `enterprise` plan until a date                      |

There is no `subscriptions.cancel` permission, so cancel uses `subscriptions.update`.

- **List.** Organisations that have or had a Stripe subscription, hold an unexpired grant, or have a non-free stored
  tier. `status` is a Stripe status (`inactive`, `active`, `trialing`, `past_due`, `canceled`, `unpaid`,
  `incomplete`, `incomplete_expired`, `paused`); `plan` is `free`, `pro` or `enterprise` and filters the
  **effective** plan (below). Anything else is a 422. Newest first, id as tie-break, so paging is stable.
- **Detail.** Adds the Stripe customer and subscription ids (identifiers, not secrets) and `payments`: the
  customer's latest 12 charges read live from Stripe, money fields only (`charge_id`, `amount`, `amount_refunded`,
  `refundable`, `currency`, `status`, `created`, `invoice_id`). No card, billing or email data is parsed or returned.
  `payments` is `[]` without a Stripe customer and `null` when Stripe is unconfigured or did not answer.
- **Cancel.** Body `{"immediately": false}` (optional). Needs a live subscription (`active`, `trialing`, `past_due`,
  `unpaid`, `incomplete`, `paused`) of the organisation's own customer, else 409. Nothing is written locally; the
  webhook updates status, tier and `stripe_cancel_at_period_end` when Stripe's event arrives. Cancelling at period
  end a subscription that is already ending is a 409.
- **Refund.** Body `{"charge_id": "ch_...", "amount": 1200, "reason": "duplicate"}`. `amount` is optional, a strict
  integer in minor units (1 to 99,999,999); omitted means everything still refundable. `reason` is Stripe's
  `duplicate`, `fraudulent` or `requested_by_customer`. There is no currency field: it comes from the charge. The
  charge is fetched from Stripe and must belong to the organisation's `stripe_customer_id`; an unknown charge and
  another customer's charge return the same `404 Payment not found`. A charge that is not captured or is fully
  refunded, or an amount above what is left, is a 409 and Stripe is not asked to refund.
- **Grant.** Body `{"plan": "pro" | "enterprise", "expires_at": "<timezone-aware ISO 8601>"}`. The expiry must be
  in the future and at most 730 days away (422). Refused with 409 while the organisation has a live Stripe
  subscription, since a grant beside it could only contradict it. The same plan and expiry again is a no-op
  (`changed: false`, no audit row). There is no revoke route (a possible follow-up).

## Grant model (migration `0007`)

`organizations.granted_plan` and `granted_until` are written **only** by the grant route, apart from the
Stripe-backed `subscription_tier`/`subscription_status`, so the webhook can never overwrite or contradict a grant
and no fake Stripe object exists. Both are NULL together or set together (CHECK constraints); existing rows have no
grant; the downgrade drops the columns. The plan in force is `effective_plan_key` (`app/core/plans.py`): the higher
of the Stripe tier and an unexpired grant. It feeds the admin list, detail and `plan` filter (a SQL twin in
`AdminSubscriptionsRepository`, kept equal by an e2e test), the organisation billing summary
(`OrgBillingRepository.get`) and the store limit (`OrganizationsRepository`), so a grant takes effect for the
merchant until it expires.

## Money safety

- **Idempotency.** Cancel and refund require an `Idempotency-Key` header (8 to 64 of `A-Za-z0-9_-`; otherwise 422
  before anything happens). The Stripe key is deterministic: `sc-admin-<cancel|refund>-<organisation id>-<client
  key>`. An advisory lock serialises requests with one key, and the audit row, found by a SHA-256 of the key (the
  key itself is never stored), tells a retry the work is done: same result with `already_applied: true`, no Stripe
  call, no second audit row. Reusing a key for another request (amount, charge or cancel mode) is a 409. If the
  audit commit fails after Stripe accepted, the request is a 500; the retry makes Stripe replay its answer (the
  same refund) and writes the audit row then.
- **Audit (KAN-49).** One row per change: `admin.subscriptions.cancel`, `.refund`, `.grant`, `resource`
  `subscriptions`, `resource_id` and `organization_id` the organisation, details sanitized (ids and amounts, no card
  data). Grant and its audit row share one transaction; Stripe cannot join one, so cancel and refund stage the row
  after Stripe accepted.
- **Errors.** No Stripe text reaches a response or log. 502 `Billing provider unavailable` for an outage, 409
  `The billing provider refused the request` when Stripe rejects the request itself (HTTP 400, 402, 409), 503 when
  `STRIPE_SECRET_KEY` is unset (reads still work).

## Stripe client

`app/core/stripe_admin.py`: `StripeAdminBilling` (Protocol) and `HttpStripeAdmin`, a subclass of the organisation
billing client adding `list_charges`, `get_charge`, `create_refund` and `cancel_subscription` (DELETE). The router
dependency `stripe_admin` returns `None` without a key. Tests override it with
`tests/fakes_admin_subscriptions.py:FakeStripeAdmin` and never call Stripe. `StripeRejected` is new in
`stripe_billing.py` (a `StripeError` subclass, so existing handlers are unaffected).

## Configuration and tests

No new environment variables (uses `STRIPE_SECRET_KEY`).

- `tests/core/test_stripe_admin.py`, `tests/core/test_effective_plan.py`: no network, no database.
- `tests/api/admin_subscriptions/`: the real app, dependency chain and Postgres, same `TEST_DATABASE_URL` contract
  as the other e2e tests. They cover 401 and 403 (non-admin, merchant owner, admin missing exactly the route's
  permission), 422 validation, success, Stripe failure and refusal, retry idempotency (also concurrent), a
  cross-organisation refund, and one audit row per change.
