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
  `unpaid`, `incomplete`, `paused`) is not required locally: Stripe's live state of the organisation's own
  subscription decides (a missing subscription or a customer mismatch is a 409). Nothing is written locally; the
  webhook updates status, tier and `stripe_cancel_at_period_end` when Stripe's event arrives. If Stripe already
  shows the requested end state (ending at period end, or ended for an immediate cancel) no Stripe call is made
  and the request is still audited, which is what lets a retry after a lost audit row succeed. A period-end cancel
  of a subscription Stripe shows as ended is a 409.
- **Refund.** Body `{"charge_id": "ch_...", "amount": 1200, "reason": "duplicate"}`. `amount` is required, a strict
  integer in minor units (1 to 99,999,999), so a retry sends Stripe an identical request. `reason` is Stripe's
  `duplicate`, `fraudulent` or `requested_by_customer`. There is no currency field: it comes from the charge. The
  charge is fetched from Stripe and must belong to the organisation's `stripe_customer_id`; an unknown charge and
  another customer's charge return the same `404 Payment not found`. An amount above what is left
  refundable (including a charge that is not captured or already fully refunded) is a 409: Stripe enforces the
  balance and refuses, so no money moves.
- **Grant.** Body `{"plan": "pro" | "enterprise", "expires_at": "<timezone-aware ISO 8601>"}`. The expiry must be
  in the future and at most 730 days away (422). Refused with 409 while the organisation has a live Stripe
  subscription, since a grant beside it could only contradict it. The same plan and expiry again is a no-op
  (`changed: false`, no audit row). Revocation is not implemented (a follow-up story).

## Grant model (migration `0007`)

`organizations.granted_plan` and `granted_until` are written **only** by the grant route, apart from the
Stripe-backed `subscription_tier`/`subscription_status`, so the webhook can never overwrite or contradict a grant
and no fake Stripe object exists. Both are NULL together or set together (CHECK constraints); existing rows have no
grant; the downgrade drops the columns. The plan in force is `effective_plan_key` (`app/core/plans.py`): the higher
of the Stripe tier and an unexpired grant. It feeds the admin list, detail and `plan` filter (a SQL twin in
`AdminSubscriptionsRepository`, kept equal by an e2e test), the organisation billing summary
(`OrgBillingRepository.get`, field `effective_plan`; `subscription_tier` stays the raw Stripe value) and the store limit
(`OrganizationsRepository`, field `effective_plan`), so a grant takes effect for the merchant until it expires. A
grant is not a Stripe subscription: change plan, cancel, resume and portal still need a live Stripe subscription or
customer and answer 409 for a grant-only organisation (covered by a test); the webhook reads only the raw tier.

## Money safety

- **Idempotency.** Cancel and refund require an `Idempotency-Key` header (8 to 64 of `A-Za-z0-9_-`; otherwise 422
  before anything happens). The Stripe key is deterministic: `sc-admin-<cancel|refund>:<organisation id>:<client
  key>`. The audit row, found by a SHA-256 of the key (the key itself is never stored), tells a retry the work is
  done: same result with `already_applied: true`, no Stripe call, no second audit row. Reusing a key for another
  request (amount, charge, reason or cancel mode) is a 409; a damaged stored row is also a 409, never a 500.
  Advisory locks (never the organisation row, so the webhook is not blocked) serialise requests with one key and,
  for a refund, one charge.
- **Refund order (audit never depends on Stripe's 24 hour key window).** (1) A *pending* audit row (`state`) is
  committed before Stripe moves money. (2) Stripe is called with no transaction open, so no connection is held across
  the (up to 10 second) calls. The refund carries the request reference in its Stripe metadata (`request_ref`); a retry
  of a pending or failed row first looks for a refund with that reference and only creates one if there is none, so a
  refund whose result was not recorded is found again even after Stripe forgot the key. (3) The same row becomes
  `completed` (or `failed` when Stripe refused or was unreachable) and is committed. If recording fails after Stripe
  acted, the response is a 503 `retry with the same Idempotency-Key`. A new key is a new request. This is the only
  update of an audit row, and only of the row the service itself staged.
- **Cancel** needs no intent row: Stripe's live state decides (a subscription already ended or ending is audited
  without a second call), and the audit row is written after Stripe acted, with the same 503 retry on failure.
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
