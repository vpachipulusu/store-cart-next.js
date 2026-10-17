# Backend store migrations (KAN-57)

Every store has its own database (ADR-005), so schema changes for store data need their own migration tree, separate from
the platform tree in `fastapi_backend/alembic_migrations/` (plan decision D15).

| Tree     | Location                              | Version table           | Applied by                                  |
| -------- | ------------------------------------- | ----------------------- | ------------------------------------------- |
| platform | `fastapi_backend/alembic_migrations/` | `alembic_version`       | `alembic upgrade head` (ADR-011)            |
| store    | `fastapi_backend/alembic_store/`      | `store_alembic_version` | `app.services.store_migrations` (this page) |

Never run `alembic upgrade` against a store database by hand: the store tree has no database URL on purpose. Its
`env.py` accepts only a connection handed in by the service, which gets it from `app/services/store_sessions.py`. That
keeps every store engine and connection string behind the one permitted module (ruff TID251) and out of Alembic
configuration and logs.

## Running it

```bash
cd fastapi_backend
uv run python -m commands.migrate_stores [--batch-size 50]
```

The command needs the platform `DATABASE_URL` and `STORE_DB_ENCRYPTION_KEY` (it decrypts each store's connection string).

- Selects stores with status `ACTIVE`, in id order, `--batch-size` at a time (default 50). Stores in `PROVISIONING`,
  `SUSPENDED` or `ARCHIVED` are skipped and the output says how many per status. (A provisioning job migrates its own
  new store by calling `migrate_store`, which does not look at the status.)
- Migrates each store to the head of the store tree and writes the number of applied store revisions to
  `stores.schema_version`, one store at a time.
- **Stops on the first failure**: later stores are not touched and the exit code is 1. Fix the cause, then run it again;
  stores that already succeeded are a no-op. A store's pending revisions run in one transaction, so on failure all of
  that store's pending revisions roll back and it stays at its previous version. The run is serial and deliberately
  stops at the first failure, so one bad store blocks the stores after it in id order until it is fixed. If only the
  `schema_version` write fails (`StoreVersionNotRecorded`), the store is already migrated; re-running repairs the record.
- Output names stores by id only. A failure prints the store id and the exception class, never a connection string or a
  driver message.
- Two runners on the same store are serialised by a Postgres advisory lock.

Python API (for the provisioning job and tests):

```python
from app.services.store_migrations import migrate_store, migrate_active_stores

version = await migrate_store(store_id)          # -> new schema version (int); raises StoreMigrationFailed
report = await migrate_active_stores(batch_size=50)
```

## On deploy

`.github/workflows/migrate-stores.yml` runs the command. It is **manual only** (`workflow_dispatch`) and uses the
`production` GitHub environment, so its secrets (`DATABASE_URL_DIRECT` or `DATABASE_URL`, `STORE_DB_ENCRYPTION_KEY`,
and the previous keys while rotating) are only exposed to a run that environment approves. Because
`app.core.config` validates the whole production configuration at import, the environment also needs the other values
the deployed backend requires (Upstash, `BACKEND_INTERNAL_KEY`, `RATE_LIMIT_EMAIL_KEY`, Firebase Admin); the workflow
lists them. Nothing triggers it
automatically yet; run it after the backend deploy that ships a new store revision. Wiring it to the deploy event
needs the production secrets to exist first, so it stays a separate decision. It never runs inside a request.

The workflow maps the `DATABASE_URL_DIRECT` secret (the unpooled Neon endpoint) onto `DATABASE_URL`, falling back to the
`DATABASE_URL` secret; the app itself never reads `DATABASE_URL_DIRECT`. The `production` environment (deployment
branches: `main` only, required reviewers) and all its secrets must exist before the first run. The batch size input is a
choice of 10 to 500 (the command caps `--batch-size` at 500).

The runner has **no downgrade**: a bad revision that already shipped needs a forward fix (a new revision), never a manual
downgrade of tenant databases. A store whose database is stamped with a revision this build does not know (an older
build running during a rolling deploy) fails with `StoreSchemaAhead` and is not touched, and `schema_version` is never
lowered (`GREATEST` on write).

Waiting for another runner on the same store (a second run, or the provisioning job) is polled for up to 15 minutes (a
holder's DDL may run up to the 10 min statement timeout) and is separate from the 30 s `lock_timeout` that bounds the DDL
itself. The wait keeps one transaction open, so a store database with a short `idle_in_transaction_session_timeout` would
fail that store. Running out of wait fails the store and stops the run: re-run it. Likewise a store already migrated by a
newer build (`StoreSchemaAhead`) stops an older build's run on purpose; re-run with the new build. The check protects only
runners that take the lock; a manual out-of-band migration bypasses it. `stores.schema_version` only ever increases, so
after restoring a store from an older backup, reset it by hand.
The batch-size choices in the workflow must be kept within the command's cap (`MAX_BATCH_SIZE`, 500).

The job runs only for `refs/heads/main`. **Repository setting required before the first use:** configure the
`production` environment with "Deployment branches: main only" and required reviewers; without that, anyone with write
access could dispatch it on another branch. Migrations run as the store owner role on every tenant database, so treat
a store revision like production code. Each store is bounded by a 30 s lock timeout and a 10 min statement timeout, so a
stuck runner fails that store (and stops the run) instead of hanging.

## Compatibility rule: expand, then contract

Deploys are not atomic: while the migration runs, and until every instance has restarted, the **previous** code version
is still serving requests against the **new** schema. Therefore every store migration must be compatible with the code
that is currently deployed.

1. **Expand** (this release): add tables, add nullable columns or columns with a server default, add indexes
   (not `CREATE INDEX CONCURRENTLY`: each store revision runs inside one transaction that holds the advisory lock, so
   concurrent index builds are unsupported until a mechanism is added). Do not rename, retype, drop or add `NOT NULL` without a default.
2. Ship code that works with both shapes.
3. **Contract** (a later release, after the old code is gone): drop the old column or table, tighten constraints.

A rename is expand (add new, backfill, dual-write), then contract (drop old). A migration that the previous code
cannot survive is a bug in the migration, not in the deploy.

## Adding a store migration

```bash
cd fastapi_backend
uv run alembic -c alembic_store.ini revision -m "add widgets" --rev-id 0002
```

`alembic_store.ini` is used only to author the file. Revision ids are the zero-padded sequence (`0002`, `0003`, ...)
and the tree must keep a single head. Then:

1. Edit `alembic_store/versions/0002_add_widgets.py` (`upgrade` and a working `downgrade`). There is no model
   metadata and no autogenerate: write the operations by hand with `op.*`.
2. Add a test next to `tests/services/test_store_migrations_e2e.py` that migrates a throwaway store database and checks
   the new objects.
3. Update the head asserted in `tests/services/test_store_migrations.py`.

`stores.schema_version` is the count of revisions applied (`0001` is 1), not the revision id.

## Testing

Unit tests (`tests/services/test_store_migrations.py`, `tests/commands/test_migrate_stores.py`) run everywhere. The
real-database module `tests/services/test_store_migrations_e2e.py` needs a throwaway Postgres 17 and is skipped when
`TEST_DATABASE_URL` is unset (CI sets it; see [testing.md](testing.md)). It creates its own platform database and store
databases and drops them afterwards.

```bash
docker run -d --rm --name store-mig-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=storemig_test -p 55460:5432 postgres:17
cd fastapi_backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55460/storemig_test \
  uv run pytest tests/services/test_store_migrations_e2e.py
docker rm -f store-mig-pg
```

## Store tables

| Revision | Adds | Doc |
| -------- | ---- | --- |
| `0001` | baseline (no tables) | this page |
| `0002` | catalogue: products, variants, options, option values (KAN-70) | [backend-store-catalogue.md](backend-store-catalogue.md) |
| `0003` | categories, product-category links, product images (KAN-71) | [backend-store-catalogue.md](backend-store-catalogue.md#categories-and-product-images-kan-71) |
| `0004` | orders and order items with purchase snapshots, status flow (KAN-78) | [backend-store-orders.md](backend-store-orders.md) |

Tests that need "a store at version 1" pass a tree that stops at `0001` (`baseline` fixture in
`tests/services/test_store_migrations_e2e.py`) instead of depending on the real head.
