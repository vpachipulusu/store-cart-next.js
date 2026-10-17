# Backend: admin organisations and stores API (KAN-201)

Platform-admin routes in `fastapi_backend` to list organisations and stores, suspend and unsuspend a store, and
re-run its migrations. Re-running provisioning is out of scope (KAN-200). The admin UI is a separate frontend story.

## Routes

All under `/v1/admin`. Every route needs `X-Internal-Key`, a verified session and a platform admin record holding the
permission below (`require_admin`: 401 without a session, one generic 403 for a non-admin, a merchant or a missing
permission). Success responses use `{"success": true, "data": ...}` and carry `Cache-Control: no-store`; error
responses do not (they hold no store data). Rate limited by subject
(`API_POLICY`). A `super_admin` holds all three permissions through the wildcard.

| Method and path                      | Permission       | Purpose                                                                  |
| ------------------------------------ | ---------------- | ------------------------------------------------------------------------ |
| `GET  /organizations`                | `stores.read`    | Page: `search` (name or slug), `limit` 1-100 (default 20), `offset`      |
| `GET  /stores`                       | `stores.read`    | Page: filters `status`, `organization_id`, `search` (name or slug)       |
| `POST /stores/{store_id}/suspend`    | `stores.suspend` | ACTIVE to SUSPENDED                                                      |
| `POST /stores/{store_id}/unsuspend`  | `stores.suspend` | SUSPENDED to ACTIVE                                                      |
| `POST /stores/{store_id}/migrate`    | `stores.migrate` | Run `migrate_store` (KAN-57); returns the previous and new `schema_version` |
| `POST /stores/{store_id}/reprovision` | `stores.reprovision` | Re-run provisioning of a `FAILED` store (KAN-200) |

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
- **Concurrency and cancellation.** The single-flight check and claim share no `await`, so two requests in one process
  cannot both start. The status check in migrate is unlocked but benign: ACTIVE and SUSPENDED are both allowed, so a
  concurrent suspend or unsuspend cannot change whether the migration may run. When the 60 second deadline expires
  (`asyncio.timeout`; only the deadline counts as a timeout, any other error is a 502) the store session is cancelled:
  its transaction rolls back, its connection closes and the transaction-scoped advisory lock is released
  (`test_a_cancelled_store_session_rolls_back_and_releases_its_lock` checks this on Postgres). A request cancelled
  mid-migration (the client disconnected) writes no audit row, because cancellation skips the audit step; re-running
  is safe because the upgrade is idempotent.
- **Audit details.** `details.reason` exists only on `admin.stores.migrate_failed` rows (the exception class and
  SQLSTATE, or the timeout and version-not-recorded texts); the other three actions carry `before` and `after` only.
- **Errors.** 502 is a generic body. 503 means retry: `Retry-After: 30` for a timeout, `5` when the change or its
  audit row could not be committed (a status change is rolled back; a migration may need a re-run).
- **Rate limit.** Migrate shares the generic per-subject `API_POLICY` with the read routes. A stricter limit for it
  is deliberately not part of this story; the per-store single-flight guard and the 60 second bound are the only
  protection against many concurrent migrations by one admin.
- **Limits.** The single-flight guard is per process: a second worker that gets the same store waits on the
  per-database advisory lock instead of answering 409 (bounded by the 60 second deadline). A migration is logged when
  it starts and when it finishes (`store_id`, `admin_user_id`), because a request that dies mid-migration writes no
  audit row. `ILIKE '%term%'` search and deep `offset` values are not indexed; both are fine at current sizes.

## Re-running provisioning (KAN-200)

- **Flow.** Under the store row lock the store must be `FAILED` (else 409). In one transaction the status becomes
  `PROVISIONING` and an `admin.stores.reprovision` audit row (`before`/`after` status, `details.attempt`,
  `details.max_attempts`) is written. Only after the commit is `create_database` enqueued with `start_provisioning`, so
  a delivery never sees `FAILED`. Concurrent requests: one wins, the rest get 409.
- **Cap.** `MAX_REPROVISION_ATTEMPTS` (3, `app/services/admin_stores.py`; **not confirmed by the owner**). There is no
  `provisioning_attempts` column, so the attempts are the store's earlier `admin.stores.reprovision` audit rows
  (`AdminStoresRepository.count_reprovisions`, indexed by `store_id`). Past the cap: 409 "Provisioning retry limit
  reached". Audit rows are never deleted, so the cap is per store for good; raising the constant lifts it.
- **Orphan database: reused, not dropped.** The failed run's database and encrypted connection string stay on the store.
  Every step is idempotent (the provisioner returns an existing database, an existing connection string is never
  overwritten, migrations are idempotent), so the retry simply continues. Nothing destructive runs on an admin click.
- **Enqueue failure.** 502 "Provisioning could not be started". The store is `FAILED` again (`start_provisioning`) and an
  `admin.stores.reprovision_failed` audit row cancels the attempt in the count, so an outage does not use up the cap. If
  marking `FAILED` also crashes the store can stay `PROVISIONING` (logged); the enqueue is shielded from request
  cancellation to keep that rare.
- **Dedup window.** The first step of a re-run is published with its own dedup id (`provision-<id>-create_database-a<n>`),
  so QStash never drops it. The later steps keep `provision-<id>-<step>`: QStash collapses a publish of the same id within
  about 10 minutes, so if a previous run published `run_migrations` or `mark_ready` that recently, a quick re-run can lose
  that step and the store stays `PROVISIONING` (see the stuck `PROVISIONING` query in `backend-store-provisioning-job.md`).
  Wait about 10 minutes after a failure before re-running.
- **Stale callbacks.** `mark_failed` has no run token: a late failure callback or duplicate delivery of the previous run
  can flip the new run back to `FAILED`. Known limitation; re-run again.
- **Retention.** The cap counts audit rows, so any audit purge must keep `admin.stores.reprovision*` rows or the cap resets.
- **Permission.** `stores.reprovision` is new; `super_admin` has it through the wildcard, every other admin needs it granted explicitly (nothing seeds it).
