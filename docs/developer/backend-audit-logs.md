# Tenant-aware audit log (KAN-49)

Every admin or merchant change writes one row to `audit_logs`; platform admins read them through one list endpoint.
The admin UI is KAN-50. App settings, feature flags, email templates, SEO meta, redirects and system stats are out
of scope (KAN-114).

## Row shape

`audit_logs` has `user_id`, `organization_id` and `store_id` (added by migration `0006`; none is a foreign key, so
rows outlive users, organisations and stores), `action` (`<area>.<verb>`), `resource`, `resource_id`, a small
`metadata` JSON (`before`, `after`, `details`, `request_id`, `actor_role`), `ip_address` and `user_agent` (admin
routes only). `store_id` is set only for store-scoped actions. Metadata passes through `app.services.audit.sanitize`
(secret-looking keys and values are redacted, size is bounded). Never log bodies, tokens, card data, Stripe
customer ids, return URLs or connection strings.

Indexes for the list filters: `(user_id, created_at)`, `(action, created_at)`, `(organization_id, created_at)`,
`(store_id, created_at)` and `(created_at)`.

## Covered actions

| Action | Written by | Organisation | Store |
| --- | --- | --- | --- |
| `admin.users.update`, `.delete`, `.ban`, `.unban`, `.grant_admin`, `.revoke_admin` | `AdminUsersService` | no | no |
| `org.create`, `org.update` | `OrganizationsService` | yes | no |
| `store.create`, `store.update` | `OrganizationsService` | yes | yes |
| `billing.checkout`, `billing.change_plan`, `billing.cancel`, `billing.resume` | `OrgBillingService` | yes | no |
| `billing.delete_payment_method`, `billing.set_default_payment_method` | `OrgBillingService` | yes | no |

Transactions: the organisation, store and admin-user rows are staged in the same transaction as the change, so
both commit or both roll back. Billing changes happen at Stripe, which cannot join a database transaction: the row
is written after Stripe accepts the change. If that write fails the request returns 500 and the change stands at
Stripe. Refused or failed requests (403, 404, 409, 502) write no row.

Not audited, on purpose: reads, opening the billing portal (no change is made by the call itself), Stripe webhook
processing (system driven, recorded in `stripe_events`), sign-in and session refresh (login history), and a user's
own profile, settings and two-factor changes (account level, not an admin or merchant change). Add them in a
follow-up story if the owner wants them.

## API

`GET /v1/admin/audit-logs`, permission `audit.read` (a `super_admin` with `*` holds it). 401 without a session,
403 for a non-admin, an admin without the permission and every merchant, including the owner of the organisation.

Query: `organization_id`, `store_id`, `user_id` (exact ids), `action` (exact, for example `store.update`), `limit`
(1 to 100, default 50), `offset` (0 to 1,000,000). Newest first. Response:
`{success, data: {entries: [...], total_count, limit, offset}}` with `Cache-Control: no-store`. Listing writes no row.

Tests: `tests/api/test_audit_logs_e2e.py` (real Postgres via `TEST_DATABASE_URL`, includes the 0006 downgrade
check), the audit assertions in `test_organizations_e2e.py` and `test_org_billing_e2e.py`, and the unit tests in
`tests/services/test_audit*.py` and `test_org_billing.py`.
