# Platform admin analytics and Stripe sync (KAN-119)

Routes under `/v1/admin/analytics`, all platform-admin only (`require_admin`, then no-store):

| Route | Permission | Returns |
|---|---|---|
| `GET /overview` | `users.read` | user counts (total, verified, new this month, active in 30 days, admins), organisation counts, stores by status |
| `GET /revenue` | `subscriptions.read` | MRR and ARR in minor units, per-plan split, organisations by status and tier, cancelling and granted counts |
| `GET /system` | `settings.read` | row counts of settings, flags, templates, SEO, redirects, audit logs, Stripe events, admins |
| `POST /subscription-sync` | `subscriptions.sync` | drift report between Stripe and the organisations table; one audit row |

No migration and no model change: everything reads existing tables.

## Revenue

Computed from organisation billing data, never one Stripe call per customer. Organisations in `active` or
`past_due` are grouped by `stripe_price_id` in one query. Each *configured* price id
(`STRIPE_PRICE_ID_*`) is read once from Stripe for its unit amount; yearly prices count as one twelfth per month.
Trials pay nothing yet and are not revenue. A billed organisation whose price id is not configured or whose price
cannot be read is counted in `unpriced_organizations` and `complete` is `false` (the totals are then a floor).
The figure is **list-price MRR**: subscription quantity, coupons, tax and the price's own currency are not modelled;
the currency is the platform `currency` setting. The request's database transaction is ended before the Stripe
price reads, so no connection is held during them. Admin grants (`granted_plan`) are complimentary and never revenue.

## Stripe sync

Reads all Stripe subscriptions (`status=all`, 100 per page, at most 20 pages) and compares them with the
organisations. It **reports and does not write**: the webhook (KAN-44) stays the single writer of subscription
state, so a sync can never overwrite newer webhook data with an older read. Drift kinds: `unmatched` (no
organisation), `subscription_id`, `status`, `plan`, `cancel_at_period_end`, `missing_in_stripe` (organisation
claims a live subscription Stripe does not have; skipped when the read was truncated). Ended subscriptions of a
customer who has a newer one are counted as `historical_ignored`. At most 100 drift items are returned; the
counts are complete. The read transaction is ended before Stripe is called, so no connection is held during
Stripe calls. Limits: 20 pages (2000 Stripe subscriptions) and 10,000 local billed organisations; hitting either
sets `truncated` and skips the `missing_in_stripe` check. The sync is rate limited to 3 runs a minute per admin.
A webhook that lands between the Stripe read and the database read can show as transient drift; re-run to confirm.
Audit action `admin.subscriptions.sync` (counts and an outcome, no customer data), written for failed Stripe
reads too (`outcome: unavailable`). Errors: 502 Stripe failed, 503 no key (not audited).

Tests: `tests/services/test_admin_analytics.py`, `tests/core/test_stripe_sync.py`, and the real-Postgres
`tests/api/admin_analytics/` (needs `TEST_DATABASE_URL`, see `backend-admin-subscriptions.md`).
