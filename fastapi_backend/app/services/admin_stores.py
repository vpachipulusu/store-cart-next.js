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
* Failures carry a class name and SQLSTATE only (``safe_reason``), never a driver
  message or a connection string.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import NoReturn, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AdminContext
from app.models.platform.store import StoreStatus
from app.repositories.admin_stores import (
    OrganizationPage,
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
TIMEOUT_REASON = "timeout (outcome unknown; re-run to repair)"

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


class CommitFailed(Exception):
    """The change or its audit row could not be committed (503, retry)."""


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
    async def set_status(self, store_id: str, status: StoreStatus) -> None: ...


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


@dataclass(frozen=True)
class MigrateResult:
    previous_version: int
    schema_version: int


class AdminStoresService:
    def __init__(
        self,
        repository: StoresStore,
        session: AsyncSession,
        auditor: AuditRecorder,
        migrate: Callable[[str], Awaitable[int]],
        timeout: float = MIGRATE_TIMEOUT_SECONDS,
    ) -> None:
        self.repository, self.session, self.auditor = repository, session, auditor
        self._migrate, self.timeout = migrate, timeout

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

    async def migrate(self, actor: AdminContext, store_id: str) -> MigrateResult:
        record = await self.repository.get_store(store_id)
        if record is None:
            await self._abort(AdminStoreNotFound())
        # Check and claim with no await in between: two requests cannot both pass.
        if record.status not in MIGRATABLE_STATUSES or store_id in _migrating:
            await self._abort(StoreConflict())
        _migrating.add(store_id)
        context = {"store_id": store_id, "admin_user_id": actor.user_id}
        try:
            # End the read transaction: no connection is held while the store is migrated.
            try:
                await self.session.rollback()
            except Exception as exc:  # noqa: BLE001
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
    ) -> None:
        """Audit an outcome and commit it, with the status change if any, in one transaction.

        A failure is a 503 telling the admin to retry: a migration is idempotent and a
        status change was rolled back.
        """
        try:
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
                details={"reason": reason} if reason else None,
            )
            await self.session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "admin store outcome was not recorded: %s",
                safe_reason(exc),
                extra={
                    "store_id": record.id,
                    "action": action,
                    "admin_user_id": actor.user_id,
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

    async def _abort(self, error: Exception) -> NoReturn:
        """Release the row lock, then leave without a change."""
        await self._safe_rollback({})
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
            await self._abort(AdminStoreNotFound())
        if record.status is target:
            await self._safe_rollback({"store_id": store_id})
            return StatusResult(target, changed=False)
        if record.status is not source:
            await self._abort(StoreConflict())
        await self._record(
            actor,
            record,
            action,
            before={"status": source.value},
            after={"status": target.value},
            new_status=target,
        )
        return StatusResult(target, changed=True)
