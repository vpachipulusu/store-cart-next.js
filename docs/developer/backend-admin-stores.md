# Backend: admin organisations and stores API (KAN-201)

Platform-admin routes in `fastapi_backend` to list organisations and stores, suspend and unsuspend a store, and
re-run its migrations. Re-running provisioning is out of scope (KAN-200). The admin UI is a separate frontend story.

## Routes

All under `/v1/admin`. Every route needs `X-Internal-Key`, a verified session and a platform admin record holding the
permission below (`require_admin`: 401 without a session, one generic 403 for a non-admin, a merchant or a missing
permission). Responses use `{"success": true, "data": ...}` and `Cache-Control: no-store`. Rate limited by subject
(`API_POLICY`). A `super_admin` holds all three permissions through the wildcard.

| Method and path                      | Permission       | Purpose                                                                  |
| ------------------------------------ | ---------------- | ------------------------------------------------------------------------ |
| `GET  /organizations`                | `stores.read`    | Page: `search` (name or slug), `limit` 1-100 (default 20), `offset`      |
| `GET  /stores`                       | `stores.read`    | Page: filters `status`, `organization_id`, `search` (name or slug)       |
| `POST /stores/{store_id}/suspend`    | `stores.suspend` | ACTIVE to SUSPENDED                                                      |
| `POST /stores/{store_id}/unsuspend`  | `stores.suspend` | SUSPENDED to ACTIVE                                                      |
| `POST /stores/{store_id}/migrate`    | `stores.migrate` | Run `migrate_store` (KAN-57); returns the previous and new `schema_version` |

- **Lists** return `status` and `schema_version` per store, and the store count per organisation. They never return
  `database_ref` or the connection string. Newest first, id as tie-break. Unknown `status` or malformed ids are a 422.
- **Suspend and unsuspend** lock the store row. A store already in the target state is a 200 with `changed: false`,
  no write and no audit row. PROVISIONING and ARCHIVED stores are a 409. A suspended store disappears from the
  storefront lookup (it needs ACTIVE) and merchant writes are refused (KAN-61); unsuspending restores both.
- **Migrate** works for ACTIVE and SUSPENDED stores (a suspended store must not fall behind its schema); PROVISIONING
  belongs to the provisioning job and ARCHIVED is a 409. No platform transaction is held while the store is migrated.
  One migration per store at a time in a process (a second request is a 409); across processes the per-database
  advisory lock serialises runners. The call is bounded to 60 seconds (503 with `Retry-After`, which also covers
  waiting for another runner's lock). The migration is one transaction, so a timeout normally leaves the store at its
  previous version; if it lands after the store database committed and before `schema_version` was written, the store
  is migrated and the version is stale. The audit reason then reads "timeout (outcome unknown; re-run to repair)":
  re-running is safe (idempotent) and repairs the version. A failure is a generic 502: the audit row carries the
  exception class and SQLSTATE only (`safe_reason`), never a driver message or connection string.
  `previous_schema_version` and the audit `before` value are read before the migration and are best-effort.
- **`store_count`** on an organisation counts every store row, whatever its status.
- **Audit.** `admin.stores.suspend`, `admin.stores.unsuspend`, `admin.stores.migrate` (before/after) and
  `admin.stores.migrate_failed` (reason), each with `store_id` and `organization_id`. A change and its audit row
  commit together; a failed or timed-out migration writes its failure row after the migration ended.
  If the audit row of a finished migration cannot be written, the admin gets a 503 (re-run) and the failure is logged
  with the store id and admin id; the store database cannot be rolled back with the platform audit write.
- **Cancelled requests.** A request cancelled mid-migration (client disconnect, shutdown) writes no audit row, and
  neither does a process that dies. Re-running is safe: the upgrade is idempotent and re-stamps `schema_version`. By
  design the store DDL, the advisory lock (`pg_try_advisory_xact_lock`) and the timeouts share one store transaction,
  so a cancelled store session rolls back and its lock goes with it; this is not covered by an automated test (the
  cancel path needs a provisioned store database), so treat it as expected rather than verified. The 60 second deadline
  uses `asyncio.timeout()`, so a `TimeoutError` raised inside the migration is audited as an ordinary failure (502),
  not as a deadline expiry. An unexpected error is audited with its class name and is a 502.
- **Audit details.** `details.reason` appears only on `admin.stores.migrate_failed` rows. The status check in `migrate`
  is unlocked, which is benign because both ACTIVE and SUSPENDED stores may be migrated.
- **Failed commits.** If a suspend or unsuspend (or the audit row of a migration) cannot be committed, the transaction
  is rolled back, the failure is logged with a safe reason and the admin gets a 503 with `Retry-After: 5`.
