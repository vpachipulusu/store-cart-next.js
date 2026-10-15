# Tenant-aware audit log (KAN-49)

Every admin or merchant change writes one row to `audit_logs`; platform admins read them through one list endpoint.
The admin UI is KAN-50. App settings, feature flags, email templates, SEO meta, redirects and system stats are out
of scope (KAN-114).

## Row shape

`audit_logs` has `user_id`, `organization_id` and `store_id` (added by migration `0006`; none is a foreign key, so
rows outlive users, organisations and stores), `action` (`<area>.<verb>`), `resource`, `resource_id`, a small
`metadata` JSON (`before`, `after`, `details`, `request_id`, `actor_role`), `ip_address` and `user_agent` (admin
routes and billing routes). `store_id` is set only for store-scoped actions. Metadata passes through `app.services.audit.sanitize`
(secret-looking keys and values are redacted, size is bounded). Never log bodies, tokens, card data, Stripe
customer ids, return URLs or connection strings.

### Metadata shape

`metadata` is a JSON object (or null on very old rows), always sanitised. Keys, all optional: `actor_role`
(admin routes), `request_id` (admin and billing routes), `before` and `after` (changed fields only) and
`details` (small extra facts such as `plan`, `interval` or a payment method id). Redacted values read
`[REDACTED]`; an over-long object ends with `_truncated` or `[TRUNCATED]`. Rows written before KAN-49 are not
re-sanitised (out of scope).

### Indexes and query cost

Indexes for the list filters: `(user_id, created_at)`, `(action, created_at)`, `(organization_id, created_at)`,
`(store_id, created_at)` and `(created_at)` (the first two come from migration `0001`, so KAN-193 needed no new
index and no migration). `created_from` / `created_to` use the `created_at` columns of those indexes.

Known costs, accepted before launch: each page runs one `count(*)` over the filtered rows (an index range scan;
cheap while the table is small, linear in the matching rows later), and `OFFSET` pagination reads and discards
the skipped rows, so `offset` is capped at 10,000. Narrow the filters or the date range to reach older rows. If the
table grows into the millions, switch to keyset pagination on `(created_at, id)` and drop the exact total.
Migration `0006` builds its indexes without `CONCURRENTLY`, which blocks writes during the build: fine at
pre-launch size; any later index on a large table must be built `CONCURRENTLY` in an autocommit block with
`if_not_exists` and a matching downgrade.

## Covered actions

| Action | Written by | Organisation | Store |
| --- | --- | --- | --- |
| `admin.users.update`, `.delete`, `.ban`, `.unban`, `.grant_admin`, `.revoke_admin` | `AdminUsersService` | no | no |
| `admin.subscriptions.cancel`, `.refund`, `.grant` | `AdminSubscriptionsService` | yes | no |
| `org.create`, `org.update` | `OrganizationsService` | yes | no |
| `store.create`, `store.update` | `OrganizationsService` | yes | yes |
| `billing.checkout`, `billing.change_plan`, `billing.cancel`, `billing.resume` | `OrgBillingService` | yes | no |
| `billing.delete_payment_method`, `billing.set_default_payment_method` | `OrgBillingService` | yes | no |

Transactions: the organisation, store and admin-user rows are staged in the same transaction as the change, so
both commit or both roll back. Billing changes happen at Stripe, which cannot join a database transaction: the row
is written after Stripe accepts the change. If that write fails (KAN-193) the session is rolled back, an error is
logged with `organization_id`, `audit_action` and the Stripe `idempotency_key`, and the request still succeeds,
because the change stands at Stripe and a 500 would invite a repeat. Operators reconcile from that log line and the
Stripe webhook (the source of truth for subscription state). Billing rows carry the client IP, user agent and
request id, like admin rows. A client that retries a plan change, cancel, resume or checkout without an `Idempotency-Key` gets a fresh Stripe key, as before.
Admin refunds write an intent row before calling Stripe (KAN-48). Refused or failed requests (403, 404, 409, 502) write no row.

Not audited, on purpose: account deletion (`DELETE /v1/me`; the user's own, account-level action, like profile and
two-factor changes), reads, opening the billing portal (no change is made by the call itself), Stripe webhook
processing (system driven, recorded in `stripe_events`), sign-in and session refresh (login history), and a user's
own profile, settings and two-factor changes (account level, not an admin or merchant change). Add them in a
follow-up story if the owner wants them.

## API

`GET /v1/admin/audit-logs`, permission `audit.read` (a `super_admin` with `*` holds it). 401 without a session,
403 for a non-admin, an admin without the permission and every merchant, including the owner of the organisation.

Query: `organization_id`, `store_id`, `user_id` (exact ids), `action` (exact, for example `store.update`),
`created_from` / `created_to` (ISO 8601, inclusive; 422 when `created_from` is after `created_to`), `limit`
(1 to 100, default 50), `offset` (0 to 10,000). Newest first. Response:
`{success, data: {entries: [...], total_count, limit, offset}}` with `Cache-Control: no-store`. Listing writes no row.

Tests: `tests/api/test_audit_logs_e2e.py` (real Postgres via `TEST_DATABASE_URL`, includes the 0006 downgrade
check), the audit assertions in `test_organizations_e2e.py` and `test_org_billing_e2e.py`, and the unit tests in
`tests/services/test_audit*.py` and `test_org_billing.py`.
