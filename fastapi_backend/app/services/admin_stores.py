"""Platform-admin store management (KAN-201): list, suspend, unsuspend, re-run migrations.

* Suspend and unsuspend lock the store row, change ``status`` and stage the audit row in
  the same transaction (commit once, after ``record``; see ``app.services.audit``). A
  request that finds the store already in the target state changes nothing and writes
  no audit row; every early exit rolls back first so the row lock is not held on.
* Only ACTIVE and SUSPENDED stores can be migrated: PROVISIONING belongs to the
  provisioning job and ARCHIVED stores are gone. No platform transaction is held while
  the store database is migrated, the wait is bounded, and the outcome (success or a
  failure with a safe reason) is audited afterwards. A timeout normally leaves the store
  at its previous version (the DDL is one transaction), but if it lands after the store
  database committed and before ``schema_version`` was written, the store is migrated and
  the version is stale: the audit reason says the outcome is unknown, and re-running
  repairs it because the upgrade is idempotent.
* One migration per store at a time in this process; a second request gets a 409. The
  check and the claim share no ``await``, so two requests cannot both pass. Across
  processes the per-database advisory lock serialises runners.
* The status check in ``migrate`` is unlocked: ACTIVE and SUSPENDED are both allowed, so
  a concurrent suspend or unsuspend cannot change the outcome. A request cancelled
  mid-migration (client disconnect) writes no audit row; re-running is safe.
* Only the deadline expiring is reported as a timeout (``asyncio.timeout``); any other
  unexpected error is audited as ``migrate_failed`` with ``safe_reason`` and becomes a 502.
* Re-running provisioning (KAN-200) takes the store row lock, requires ``FAILED``, counts the
  earlier ``admin.stores.reprovision`` audit rows of the store (the cap; there is no
  attempts column, so no migration) and, in one transaction, sets ``PROVISIONING`` and
  audits. Only after that commit is the job enqueued, so a delivery never sees ``FAILED``.
  The orphan database of the failed run is reused, not dropped: every step is idempotent
  (the provisioner returns the existing database and rotates its role's password,
  the stored connection string is replaced with the new one, migrations are idempotent). If the enqueue fails the store is ``FAILED``
  again (``start_provisioning``) and an ``admin.stores.reprovision_failed`` row (which also sets ``FAILED``) frees
  the attempt's slot in the cap but not its number. Enqueue and compensation are shielded from request cancellation.
* Failures carry a class name and SQLSTATE only (``safe_reason``), never a driver
  message or a connection string.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AdminContext
from app.models.platform.store import StoreStatus
from app.repositories.admin_stores import (
    MERCHANT_RETRY_ACTION,
    MERCHANT_RETRY_FAILED_ACTION,
    REPROVISION_ACTION,
    REPROVISION_FAILED_ACTION,
    OrganizationPage,
    ReprovisionCounts,
    StoreFilters,
    StorePage,
    StoreRecord,
)
from app.services.store_migrations import (
    StoreMigrationFailed,
    StoreVersionNotRecorded,
    safe_reason,
)

MAX_PAGE_SIZE = 100
MIGRATE_TIMEOUT_SECONDS = 60.0
MIGRATABLE_STATUSES = frozenset({StoreStatus.ACTIVE, StoreStatus.SUSPENDED})

SUSPEND_ACTION = "admin.stores.suspend"
UNSUSPEND_ACTION = "admin.stores.unsuspend"
MIGRATE_ACTION = "admin.stores.migrate"
MIGRATE_FAILED_ACTION = "admin.stores.migrate_failed"
FAIL_STUCK_ACTION = "admin.stores.fail_stuck"
# A store PROVISIONING without any change for this long is stuck (KAN-248). The whole
# chain takes seconds, and QStash retries within minutes.
STUCK_AFTER = timedelta(minutes=15)
MAX_STUCK_LISTED = 100
STUCK_REASON = "no progress while PROVISIONING"
# Re-runs allowed per store. Not confirmed by the owner (KAN-200): raise or lower here.
MAX_REPROVISION_ATTEMPTS = 3
TIMEOUT_REASON = "timeout (outcome unknown; re-run to repair)"
# The 409 body when the cap is reached. The frontend matches this exact text
# (nextjs-frontend/src/lib/api/onboarding.ts) to tell it from "not FAILED"; change both together.
RETRY_LIMIT_MESSAGE = "Provisioning retry limit reached"

logger = logging.getLogger("storecart.admin_stores")
# Store ids being migrated by this process.
_migrating: set[str] = set()


class AdminStoreNotFound(Exception):
    """No such store (404)."""


class StoreConflict(Exception):
    """The store's current status does not allow the request (409)."""


class MigrationFailed(Exception):
    """The store database could not be migrated (502). Carries no driver text."""


class MigrationTimeout(Exception):
    """The migration did not finish in time (503); the outcome is unknown, re-run."""


class RetryLimitReached(Exception):
    """The store was already re-provisioned the maximum number of times (409)."""


class ProvisioningNotStarted(Exception):
    """The job could not be enqueued; the store is FAILED again (502)."""


class CommitFailed(Exception):
    """The change or its audit row could not be committed (503, retry)."""


class _MovedOn(Exception):
    """The store left PROVISIONING before the enqueue compensation ran (internal)."""


class StoresStore(Protocol):
    async def list_organizations(
        self, search: str | None, limit: int, offset: int
    ) -> OrganizationPage: ...
    async def list_stores(
        self, filters: StoreFilters, limit: int, offset: int
    ) -> StorePage: ...
    async def get_store(
        self, store_id: str, *, lock: bool = False
    ) -> StoreRecord | None: ...
    async def list_stuck(self, cutoff: datetime, limit: int) -> list[StoreRecord]: ...
    async def set_status(self, store_id: str, status: StoreStatus) -> None: ...
    async def claim_failed(self, store_id: str) -> bool: ...
    async def release_provisioning(self, store_id: str) -> StoreStatus | None: ...
    async def count_reprovisions(self, store_id: str) -> ReprovisionCounts: ...


class AuditRecorder(Protocol):
    async def record(
        self,
        admin: AdminContext,
        *,
        action: str,
        resource: str,
        resource_id: str | None = None,
        organization_id: str | None = None,
        store_id: str | None = None,
        before: object = None,
        after: object = None,
        details: object = None,
    ) -> None: ...


@dataclass(frozen=True)
class StatusResult:
    status: StoreStatus
    changed: bool
    # The store's public slug, so the frontend can refresh its cached storefront (KAN-75).
    slug: str | None = None


@dataclass(frozen=True)
class ReprovisionResult:
    status: StoreStatus
    attempt: int


@dataclass(frozen=True)
class ReprovisionKind:
    """Who re-runs provisioning: names the audit actions (the cap counts all of them)."""

    started_action: str
    failed_action: str
    label: str


ADMIN_RERUN = ReprovisionKind(REPROVISION_ACTION, REPROVISION_FAILED_ACTION, "admin")
MERCHANT_RETRY = ReprovisionKind(
    MERCHANT_RETRY_ACTION, MERCHANT_RETRY_FAILED_ACTION, "merchant"
)


@dataclass(frozen=True)
class StuckStoreRecord:
    store: StoreRecord
    minutes_stuck: int


@dataclass(frozen=True)
class StuckStores:
    items: list[StuckStoreRecord]
    truncated: bool


@dataclass(frozen=True)
class MigrateResult:
    previous_version: int
    schema_version: int


def _details(
    reason: str | None, extra: dict[str, object] | None
) -> dict[str, object] | None:
    details = {**(extra or {}), **({"reason": reason} if reason else {})}
    return details or None


class AdminStoresService:
    def __init__(
        self,
        repository: StoresStore,
        session: AsyncSession,
        auditor: AuditRecorder,
        migrate: Callable[[str], Awaitable[int]],
        timeout: float = MIGRATE_TIMEOUT_SECONDS,
        *,
        start_provisioning: Callable[[str, int], Awaitable[bool]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository, self.session, self.auditor = repository, session, auditor
        self._migrate, self.timeout = migrate, timeout
        self._start_provisioning = start_provisioning
        self._clock = clock

    async def list_organizations(
        self, search: str | None, limit: int, offset: int
    ) -> OrganizationPage:
        return await self.repository.list_organizations(
            search, min(max(limit, 1), MAX_PAGE_SIZE), max(offset, 0)
        )

    async def list_stores(
        self, filters: StoreFilters, limit: int, offset: int
    ) -> StorePage:
        return await self.repository.list_stores(
            filters, min(max(limit, 1), MAX_PAGE_SIZE), max(offset, 0)
        )

    async def list_stuck(self) -> StuckStores:
        """Stores PROVISIONING for longer than ``STUCK_AFTER`` without any change.

        The age is the app clock against the database's ``updated_at``: a skew of a
        minute or two moves the cutoff by that much, which the 15-minute margin absorbs.
        """
        now = self._clock()
        records = await self.repository.list_stuck(
            now - STUCK_AFTER, MAX_STUCK_LISTED + 1
        )
        return StuckStores(
            [
                StuckStoreRecord(
                    r, max(0, int((now - r.updated_at).total_seconds() // 60))
                )
                for r in records[:MAX_STUCK_LISTED]
            ],
            truncated=len(records) > MAX_STUCK_LISTED,
        )

    async def fail_stuck(self, actor: AdminContext, store_id: str) -> StatusResult:
        """PROVISIONING for over ``STUCK_AFTER`` becomes FAILED (audited).

        FAILED is what the merchant retry and the admin re-run act on. A store that
        is not PROVISIONING, or changed recently, is a conflict: the job may be alive.
        """
        record = await self.repository.get_store(store_id, lock=True)
        if record is None:
            await self._abort(AdminStoreNotFound(), store_id)
        if not self._is_stuck(record):
            await self._abort(StoreConflict(), store_id)
        await self._fail_stuck(actor, record)
        return StatusResult(StoreStatus.FAILED, changed=True, slug=record.slug)

    def _is_stuck(self, record: StoreRecord) -> bool:
        return (
            record.status is StoreStatus.PROVISIONING
            and record.updated_at < self._clock() - STUCK_AFTER
        )

    async def _fail_stuck(self, actor: AdminContext, record: StoreRecord) -> None:
        await self._record(
            actor,
            record,
            FAIL_STUCK_ACTION,
            before={"status": StoreStatus.PROVISIONING.value},
            after={"status": StoreStatus.FAILED.value},
            reason=STUCK_REASON,
            new_status=StoreStatus.FAILED,
        )

    async def suspend(self, actor: AdminContext, store_id: str) -> StatusResult:
        return await self._transition(
            actor, store_id, StoreStatus.ACTIVE, StoreStatus.SUSPENDED, SUSPEND_ACTION
        )

    async def unsuspend(self, actor: AdminContext, store_id: str) -> StatusResult:
        return await self._transition(
            actor,
            store_id,
            StoreStatus.SUSPENDED,
            StoreStatus.ACTIVE,
            UNSUSPEND_ACTION,
        )

    async def reprovision(
        self,
        actor: AdminContext,
        store_id: str,
        kind: ReprovisionKind = ADMIN_RERUN,
    ) -> ReprovisionResult:
        """Re-run provisioning of a FAILED store: the one cap-and-requeue path.

        Used by the admin route and by the merchant retry (KAN-242; ``kind`` only names
        the audit actions). The cap counts both kinds of audit row. FAILED to
        PROVISIONING is a single conditional UPDATE, so of two concurrent callers only
        one queues a chain.

        A store stuck in PROVISIONING (``STUCK_AFTER``) is failed first (KAN-248): that
        commits on its own (audit row ``admin.stores.fail_stuck``, not counted in the
        cap) and releases the row lock, which is taken again for the re-run. If the cap
        is then reached, or the enqueue fails, the store stays FAILED and the caller
        gets the 409/502: the honest state of a store that made no progress. The
        merchant route keeps its OWNER/ADMIN check; only the identity in the audit rows
        is shared.
        """
        record = await self.repository.get_store(store_id, lock=True)
        if record is None:
            await self._abort(AdminStoreNotFound(), store_id)
        if self._is_stuck(record):
            # The job gave up silently (KAN-248): fail it first, then re-run it.
            await self._fail_stuck(actor, record)
            refreshed = await self.repository.get_store(store_id, lock=True)
            if refreshed is None:
                await self._abort(AdminStoreNotFound(), store_id)
            record = refreshed
        if record.status is not StoreStatus.FAILED:
            await self._abort(StoreConflict(), store_id)
        counts = await self.repository.count_reprovisions(store_id)
        if counts.started - counts.failed >= MAX_REPROVISION_ATTEMPTS:
            await self._abort(RetryLimitReached(), store_id)
        # Monotonic: a failed enqueue frees its slot in the cap, never its number, so
        # no two runs of a store share an attempt (and so a QStash dedup id).
        attempt = counts.started + 1
        await self._record(
            actor,
            record,
            kind.started_action,
            before={"status": StoreStatus.FAILED.value},
            after={"status": StoreStatus.PROVISIONING.value},
            claim_failed=True,
            extra={"attempt": attempt, "max_attempts": MAX_REPROVISION_ATTEMPTS},
        )
        logger.info(
            "store provisioning re-run",
            extra={
                "store_id": store_id,
                "actor_user_id": actor.user_id,
                "attempt": attempt,
                "kind": kind.label,
            },
        )
        # Shielded: a client disconnect after the commit must not strand the store in
        # PROVISIONING without a job, nor skip the compensation below.
        if not await asyncio.shield(self._launch(actor, record, attempt, kind)):
            raise ProvisioningNotStarted
        return ReprovisionResult(StoreStatus.PROVISIONING, attempt)

    async def _launch(
        self,
        actor: AdminContext,
        record: StoreRecord,
        attempt: int,
        kind: ReprovisionKind,
    ) -> bool:
        """Enqueue the first step. On any failure the store is FAILED again and a
        ``reprovision_failed`` row frees the attempt's slot in the cap.

        The compensation is a conditional UPDATE (``WHERE status = PROVISIONING``): a
        store the job already moved on is left alone and no failure row is written.
        """
        try:
            if await self._start_provisioning(record.id, attempt):
                return True
        except Exception as exc:  # noqa: BLE001 - treated like a refused enqueue
            logger.error(
                "store provisioning start crashed: %s",
                safe_reason(exc),
                extra={"store_id": record.id, "actor_user_id": actor.user_id},
            )
        try:
            await self._record(
                actor,
                record,
                kind.failed_action,
                before={"status": StoreStatus.PROVISIONING.value},
                after={"status": StoreStatus.FAILED.value},
                release_provisioning=True,
                extra={"attempt": attempt},
            )
        except _MovedOn:
            logger.warning(
                "store left PROVISIONING before the enqueue compensation; left as is",
                extra={"store_id": record.id, "actor_user_id": actor.user_id},
            )
        except CommitFailed:
            # The store stays PROVISIONING with no job: this line is how it is found.
            logger.error(
                "enqueue compensation was not committed; store may be stranded in "
                "PROVISIONING",
                extra={"store_id": record.id, "actor_user_id": actor.user_id},
            )
            raise
        return False

    async def migrate(self, actor: AdminContext, store_id: str) -> MigrateResult:
        record = await self.repository.get_store(store_id)
        if record is None:
            await self._abort(AdminStoreNotFound(), store_id)
        # Check and claim with no await in between: two requests cannot both pass.
        if record.status not in MIGRATABLE_STATUSES or store_id in _migrating:
            await self._abort(StoreConflict(), store_id)
        _migrating.add(store_id)
        context = {"store_id": store_id, "admin_user_id": actor.user_id}
        try:
            # End the read transaction: no connection is held while the store is migrated.
            try:
                await self.session.rollback()
            except Exception as exc:  # noqa: BLE001 - logged, then reported as a 503
                self._log_rollback_failure(exc, context)
                raise CommitFailed from None
            # The audit row is written only after the migration ends, so a request that
            # dies mid-migration leaves no row: this log line is the trace of the attempt.
            logger.info("admin store migration started", extra=context)
            version = await self._run_migration(actor, record)
        finally:
            _migrating.discard(store_id)
        await self._record(
            actor,
            record,
            MIGRATE_ACTION,
            before={"schema_version": record.schema_version},
            after={"schema_version": version},
        )
        logger.info(
            "admin store migration finished",
            extra={**context, "schema_version": version},
        )
        return MigrateResult(record.schema_version, version)

    async def _run_migration(self, actor: AdminContext, record: StoreRecord) -> int:
        """Run the migration under a deadline.

        When the deadline expires the store session is cancelled: its transaction rolls
        back, the connection returns to the pool and the transaction-scoped advisory lock
        is released with it (checked against Postgres in ``test_admin_stores_e2e``).
        """
        deadline = asyncio.timeout(self.timeout)
        try:
            async with deadline:
                return await self._migrate(record.id)
        except StoreVersionNotRecorded as failure:
            reason = f"version not recorded (re-run to repair): {failure.reason}"
            await self._record(actor, record, MIGRATE_FAILED_ACTION, reason=reason)
            raise MigrationFailed from None
        except StoreMigrationFailed as failure:
            await self._record(
                actor, record, MIGRATE_FAILED_ACTION, reason=failure.reason
            )
            raise MigrationFailed from None
        except Exception as exc:  # noqa: BLE001 - audited, then collapsed to a 502
            if isinstance(exc, TimeoutError) and deadline.expired():
                logger.warning(
                    "admin store migration timed out",
                    extra={"store_id": record.id, "admin_user_id": actor.user_id},
                )
                await self._record(
                    actor, record, MIGRATE_FAILED_ACTION, reason=TIMEOUT_REASON
                )
                raise MigrationTimeout from None
            reason = safe_reason(exc)
            logger.error(
                "admin store migration failed unexpectedly: %s",
                reason,
                extra={"store_id": record.id, "admin_user_id": actor.user_id},
            )
            await self._record(actor, record, MIGRATE_FAILED_ACTION, reason=reason)
            raise MigrationFailed from None

    async def _record(
        self,
        actor: AdminContext,
        record: StoreRecord,
        action: str,
        *,
        before: object = None,
        after: object = None,
        reason: str | None = None,
        new_status: StoreStatus | None = None,
        claim_failed: bool = False,
        release_provisioning: bool = False,
        extra: dict[str, object] | None = None,
    ) -> None:
        """Audit an outcome and commit it, with the status change if any, in one transaction.

        ``claim_failed`` makes FAILED to PROVISIONING a conditional UPDATE; losing that
        race is a ``StoreConflict``. Any other failure is a 503 telling the caller to
        retry: a migration is idempotent and a status change was rolled back.
        """
        try:
            if claim_failed and not await self.repository.claim_failed(record.id):
                raise StoreConflict
            if release_provisioning and (
                await self.repository.release_provisioning(record.id)
                is not StoreStatus.FAILED
            ):
                raise _MovedOn
            if new_status is not None:
                await self.repository.set_status(record.id, new_status)
            await self.auditor.record(
                actor,
                action=action,
                resource="stores",
                resource_id=record.id,
                organization_id=record.organization_id,
                store_id=record.id,
                before=before,
                after=after,
                details=_details(reason, extra),
            )
            await self.session.commit()
        except StoreConflict:
            await self._abort(StoreConflict(), record.id)
        except _MovedOn:
            await self._abort(_MovedOn(), record.id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "store outcome was not recorded: %s",
                safe_reason(exc),
                extra={
                    "store_id": record.id,
                    "action": action,
                    "actor_user_id": actor.user_id,
                },
            )
            await self._safe_rollback({"store_id": record.id})
            raise CommitFailed from None

    @staticmethod
    def _log_rollback_failure(exc: Exception, context: dict[str, str]) -> None:
        logger.error("admin store rollback failed: %s", safe_reason(exc), extra=context)

    async def _safe_rollback(self, context: dict[str, str]) -> None:
        """Roll back; a failing rollback is logged, never a raw 500 over the real outcome."""
        try:
            await self.session.rollback()
        except Exception as exc:  # noqa: BLE001
            self._log_rollback_failure(exc, context)

    async def _abort(self, error: Exception, store_id: str) -> NoReturn:
        """Release the row lock, then leave without a change."""
        await self._safe_rollback({"store_id": store_id})
        raise error

    async def _transition(
        self,
        actor: AdminContext,
        store_id: str,
        source: StoreStatus,
        target: StoreStatus,
        action: str,
    ) -> StatusResult:
        record = await self.repository.get_store(store_id, lock=True)
        if record is None:
            await self._abort(AdminStoreNotFound(), store_id)
        if record.status is target:
            await self._safe_rollback({"store_id": store_id})
            return StatusResult(target, changed=False, slug=record.slug)
        if record.status is not source:
            await self._abort(StoreConflict(), store_id)
        await self._record(
            actor,
            record,
            action,
            before={"status": source.value},
            after={"status": target.value},
            new_status=target,
        )
        return StatusResult(target, changed=True, slug=record.slug)
