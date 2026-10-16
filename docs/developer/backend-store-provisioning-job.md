# Store provisioning job (KAN-56)

Creating a store (`POST /v1/organizations/{id}/stores`) inserts it as `PROVISIONING`, commits, then enqueues a chain of
QStash steps. Each step is one function invocation at `POST /internal/provisioning/step`
(`app/api/v1/internal_provisioning.py`, logic in `app/services/store_provisioning_job.py`):

| Step | Does | Then |
|---|---|---|
| `create_database` | `DatabaseProvisioner.create_database`, encrypts the connection string onto the store (KAN-53), sets `database_ref` | enqueues `run_migrations` |
| `run_migrations` | `migrate_store` (KAN-57), records `schema_version` | enqueues `mark_ready` |
| `mark_ready` | `PROVISIONING` becomes `ACTIVE` | done |

## Guarantees

- **Signed.** Both routes are public; the credential is the `Upstash-Signature` JWT (HS256, current or next signing key).
  It must sign the exact body and the exact URL (`PROVISIONING_BASE_URL` + route path), so a delivery cannot be replayed
  against another route. Missing keys answer 503, a bad signature 401. See `app/core/qstash_signature.py`.
- **Idempotent.** A step does nothing unless the store is still `PROVISIONING`. The provisioner and migration runner are
  idempotent, an existing connection string is never overwritten, and QStash publishes carry a deduplication id
  (`provision-<store_id>-<step>`).
- **Retries.** A transient failure answers 500 and QStash redelivers (`PROVISIONING_STEP_RETRIES`, default 5). A permanent
  one (bad store id, unusable encryption key) sets `FAILED` at once and answers 200. A provider that is not configured yet is retried, so variables that land a minute late do not fail stores.
  When retries run out QStash calls `POST /internal/provisioning/failed` (the failure callback) and the store becomes `FAILED`.
  If the very first publish fails, store creation returns the store as `FAILED`.
- **No secrets in transit.** Payloads are `{"store_id", "step"}` only. Logs carry the store id, step and exception class,
  never a connection string, token or key.
- **One invocation per step.** Each step is a single provisioner call or a single migration run (the migration runner has its
  own lock and statement timeouts). Set the function `maxDuration` for the backend service to cover a full migration.

`FAILED` is a new `stores.status` value (migration `0008`, CHECK constraint only). Recovering a `FAILED` store (re-enqueue
or archive) is an operator action and not part of this story.

## Configuration

| Variable | Purpose |
|---|---|
| `QSTASH_TOKEN` | Publishes steps (secret). Unset in local/test means nothing is enqueued; elsewhere store creation marks the store `FAILED`. |
| `QSTASH_CURRENT_SIGNING_KEY`, `QSTASH_NEXT_SIGNING_KEY` | Verify deliveries (secrets); set both so rotation is seamless. |
| `PROVISIONING_BASE_URL` | Public https origin of the FastAPI service that QStash calls back, no path. |
| `QSTASH_URL` | Optional, defaults to `https://qstash.upstash.io` (https, upstash.io hosts only). |
| `PROVISIONING_STEP_RETRIES` | Optional, 0 to 10, default 5. |

## Local development

Without `QSTASH_TOKEN` the steps are not enqueued and a new store stays `PROVISIONING`. To drive one by hand, call
`StepRunner(...).run(step, store_id)` from a shell, or run QStash locally and point `PROVISIONING_BASE_URL` at the dev server.

## Tests

`tests/core/test_qstash_signature.py`, `tests/api/test_internal_provisioning.py` and
`tests/services/test_store_provisioning_job.py` run without a database. `tests/services/test_store_provisioning_job_e2e.py`
runs the real steps against Postgres when `TEST_DATABASE_URL` is set (see `testing.md`).

## Operating notes and known gaps

- **Stuck `PROVISIONING`.** There is no sweeper. If the process dies between the store commit and the first publish, or QStash
  is down, a store can stay `PROVISIONING`. Find them with
  `SELECT id FROM stores WHERE status = 'PROVISIONING' AND created_at < now() - interval '15 minutes'`.
- **`FAILED` is terminal in this story.** No retry or re-enqueue route exists; a `FAILED` store still counts toward the plan's
  store limit and cannot be updated. A manual re-publish of a step within QStash's deduplication window is collapsed into the
  earlier message (the dedup id is `provision-<store_id>-<step>`).
- **Orphans.** A `FAILED` store may leave its database and encrypted connection string behind; nothing deletes them.
- **No audit row** is written for the `PROVISIONING` to `FAILED` / `ACTIVE` transitions (logs only).
- **Hosts.** `QSTASH_URL` must be `qstash.upstash.io` or `qstash-<region>.upstash.io`; a local QStash emulator is not accepted.
  `PROVISIONING_BASE_URL` must be the exact public origin (and path prefix, if any) the service is mounted at, or the signature
  `sub` check rejects every delivery.
- **All-or-none.** Outside local/test, setting any of `QSTASH_TOKEN`, `PROVISIONING_BASE_URL` and a signing key requires all three.
