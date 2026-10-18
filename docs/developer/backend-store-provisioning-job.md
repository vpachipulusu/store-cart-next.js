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
  own lock and statement timeouts), so one delivery never chains work. Measured on a local Postgres 17, the whole chain
  (database creation, baseline migration, activation) takes about 0.2 s; against Neon expect seconds, not minutes. No
  `maxDuration` is set in `fastapi_backend/vercel.json`: the platform default for the plan applies. Raise it in the Vercel
  project settings if a future store revision makes `run_migrations` long.
- **Non-retryable errors.** A signed request with a body that can never succeed (400 invalid payload, 413 too large) answers
  with `Upstash-NonRetryable-Error: true` so QStash drops it instead of retrying. 401 (bad signature), 500 (step failed) and
  503 (not configured) stay retryable.
- **Quota.** `FAILED` stores do not count against the plan's store limit.

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

## Production checklist (KAN-248)

A store stays `PROVISIONING` with no error when QStash accepts the first publish but the callbacks never reach this
service. In production check, in this order:

1. **Routing.** The backend service has no public route (ADR-011), so QStash can reach it only through the top-level
   rewrite `/internal/provisioning/(.*)` to `fastapi_backend` in the root `vercel.json`, placed before the catch-all.
   Without it, every delivery (and the failure callback) goes to the frontend and answers 404, so retries run out
   quietly and the store is never marked `FAILED`. This was the cause of KAN-248. `tests/core/test_vercel_routing.py`
   guards it.
2. **Variables** (Vercel project, Production scope; names only): `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY` and
   `QSTASH_NEXT_SIGNING_KEY` (copy both from the Upstash console, they rotate), `PROVISIONING_BASE_URL` (the public
   origin QStash calls, for example `https://<production domain>`, https, no path, no trailing slash, identical to the
   domain the rewrite is served on), `STORE_DB_PROVIDER=neon`, `NEON_API_KEY`, `NEON_PROJECT_ID`, `NEON_BRANCH_ID`,
   `NEON_ROLE_NAME`, `STORE_DB_ENCRYPTION_KEY`.
3. **Deployment Protection.** QStash sends no Vercel bypass header. The production domain must not be behind
   Vercel Authentication or a password; if it is, add a protection-bypass exception for `/internal/provisioning/*` or
   turn protection off for Production.
4. **Readiness.** `GET /health/ready` (header `X-Internal-Key`) returns `provisioning: {ready, missing}`; `missing` lists
   variable NAMES only. The backend also logs `store provisioning is not configured; missing: ...` at start. Neither
   can see the routing or protection problems above.

Where to look when a store is stuck (backend function logs, filter on `/internal/provisioning`):

| Evidence | Meaning |
|---|---|
| No request to `/internal/provisioning/step` at all | The rewrite is missing or deployed on another domain, protection blocks QStash, or QStash did not accept the publish (look for `qstash publish failed/rejected: status=` and `QSTASH_TOKEN and PROVISIONING_BASE_URL are not set`; that case makes the store `FAILED` at once). Check the message log in the Upstash console for the HTTP status QStash got |
| 404 (served by the frontend) in the Upstash message log | Routing (item 1) |
| 401 `Invalid signature` and `qstash signature rejected` | A signing key is wrong or rotated, or `PROVISIONING_BASE_URL` differs from the URL QStash called (host, scheme or path prefix) |
| 503 `Service temporarily unavailable` | `PROVISIONING_BASE_URL` or both signing keys are unset |
| 500 `Provisioning step failed`, plus `provisioning step failed: <ExceptionClass>` | A step raised: Neon (`ProvisionerNotConfigured`, an API error), the store database, or migrations. Retried by QStash up to `PROVISIONING_STEP_RETRIES`, then the failure callback marks the store `FAILED` |

## Stuck stores (KAN-248)

A store `PROVISIONING` with no change for 15 minutes (`STUCK_AFTER`; `updated_at` moves with every step) is stuck.

The threshold must stay above the longest single step (`updated_at` moves only when a step writes the store row), and
failing a store whose old QStash retries are still pending can let that run's late failure callback fail the re-run
(callbacks do not carry the attempt). Both are accepted for now; the 15-minute margin is large against seconds-long steps.

- `GET /v1/admin/stores/stuck` (`stores.read`) lists them, oldest first, with `minutes_stuck`.
- `POST /v1/admin/stores/{id}/fail-stuck` (`stores.reprovision`) marks one `FAILED` (audit row
  `admin.stores.fail_stuck`); 409 when it is not `PROVISIONING` or changed within 15 minutes.
- `POST /v1/admin/stores/{id}/reprovision` and the merchant's `POST /v1/stores/{id}/retry-provisioning` accept a stuck
  store: they fail it first, then re-run it (counted in the attempt cap). The onboarding status page offers "Retry setup"
  once it stops polling.

## Local development

Without `QSTASH_TOKEN` the steps are not enqueued and a new store stays `PROVISIONING`. To drive one by hand, call
`StepRunner(...).run(step, store_id)` from a shell, or run QStash locally and point `PROVISIONING_BASE_URL` at the dev server.

## Tests

`tests/core/test_qstash_signature.py`, `tests/api/test_internal_provisioning.py` and
`tests/services/test_store_provisioning_job.py` run without a database. `tests/services/test_store_provisioning_job_e2e.py`
runs the real steps against Postgres when `TEST_DATABASE_URL` is set (see `testing.md`).

## Operating notes and known gaps

- **Stuck `PROVISIONING`.** There is no automatic sweeper; operators and merchants act on stuck stores, see "Stuck stores".
- **`FAILED` retry.** A platform admin re-runs it through `POST /v1/admin/stores/{id}/reprovision` (KAN-200, see `backend-admin-stores.md`). A manual re-publish of a step within QStash's deduplication window (about 10 minutes) is
  collapsed into the earlier message (the dedup id is `provision-<store_id>-<step>-a<attempt>`; admin re-runs get a new attempt, KAN-200).
- **Orphans.** A `FAILED` store may leave its database and encrypted connection string behind; nothing deletes them. The admin re-run reuses them.
- **No audit row** is written for the `PROVISIONING` to `FAILED` / `ACTIVE` transitions (logs only).
- **Hosts.** `QSTASH_URL` must be `qstash.upstash.io` or `qstash-<region>.upstash.io`; a local QStash emulator is not accepted.
  `PROVISIONING_BASE_URL` must be the exact public origin (and path prefix, if any) the service is mounted at, or the signature
  `sub` check rejects every delivery.
- **All-or-none.** Outside local/test, setting any of `QSTASH_TOKEN`, `PROVISIONING_BASE_URL` and a signing key requires all three.
