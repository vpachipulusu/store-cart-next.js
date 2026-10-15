"""Platform-admin store management (KAN-201): list, suspend, unsuspend, re-run migrations.

* Suspend and unsuspend lock the store row, change ``status`` and stage the audit row in
  the same transaction (commit once, after ``record``; see ``app.services.audit``). A
  request that finds the store already in the target state changes nothing and writes
  no audit row.
* Only ACTIVE and SUSPENDED stores can be migrated: PROVISIONING belongs to the
  provisioning job and ARCHIVED stores are gone. No platform transaction is held while
  the store database is migrated, the wait is bounded, and the outcome (success or a
  failure with a safe reason) is audited afterwards. A timeout normally leaves the store
  at its previous version (the DDL is one transaction), but if it lands after the store
  database committed and before ``schema_version`` was written, the store is migrated and
  the version is stale: the audit reason says the outcome is unknown, and re-running
  repairs it because the upgrade is idempotent.
* One migration per store at a time in this process; a second request gets a 409. Across
  processes the per-database advisory lock serialises runners.
* Failures carry a class name and SQLSTATE only (``safe_reason``), never a driver
  message or a connection string.
* A request cancelled mid-migration (client disconnect, shutdown) writes no audit row;
  the store session rolls back with its transaction, the advisory lock is transaction
  scoped and goes with it, and re-running is safe.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

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
    """The change or its audit row could not be committed (503, retry).

    After a migration the store database is already migrated; re-running is safe.
    """


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
        # End the read transaction: no connection is held while the store is migrated.
        await self.session.rollback()
        if record is None:
            raise AdminStoreNotFound
        # The status read is unlocked, which is benign: ACTIVE and SUSPENDED both migrate.
        # Check and claim without an await in between, so two requests cannot both pass.
        if record.status not in MIGRATABLE_STATUSES or store_id in _migrating:
            raise StoreConflict
        _migrating.add(store_id)
        try:
            version = await self._run_migration(actor, record)
        finally:
            _migrating.discard(store_id)
        await self._commit_audit(
            actor,
            record,
            MIGRATE_ACTION,
            before={"schema_version": record.schema_version},
            after={"schema_version": version},
        )
        return MigrateResult(record.schema_version, version)

    async def _run_migration(self, actor: AdminContext, record: StoreRecord) -> int:
        deadline = asyncio.timeout(self.timeout)
        try:
            async with deadline:
                return await self._migrate(record.id)
        except StoreVersionNotRecorded as failure:
            reason = f"version not recorded (re-run to repair): {failure.reason}"
        except StoreMigrationFailed as failure:
            reason = failure.reason
        except Exception as exc:  # noqa: BLE001 - any other failure is audited and a 502
            if deadline.expired():
                await self._commit_audit(
                    actor, record, MIGRATE_FAILED_ACTION, reason=TIMEOUT_REASON
                )
                raise MigrationTimeout from None
            reason = safe_reason(exc)
        await self._commit_audit(actor, record, MIGRATE_FAILED_ACTION, reason=reason)
        raise MigrationFailed

    async def _commit_audit(
        self,
        actor: AdminContext,
        record: StoreRecord,
        action: str,
        *,
        before: object = None,
        after: object = None,
        reason: str | None = None,
        change: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Apply ``change`` (if any), stage the audit row and commit, in one transaction.

        Any failure rolls back, is logged with a safe reason only and becomes
        ``CommitFailed`` (a retry is safe: migrations are idempotent and a status change
        that did not commit did not happen).
        """
        try:
            if change is not None:
                await change()
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
        except Exception as exc:  # noqa: BLE001 - any recording failure means retry
            logger.error(
                "admin store action was not recorded (%s)",
                safe_reason(exc),
                extra={"store_id": record.id, "admin_user_id": actor.user_id},
            )
            await self.session.rollback()
            raise CommitFailed from None

    async def _transition(
        self,
        actor: AdminContext,
        store_id: str,
        source: StoreStatus,
        target: StoreStatus,
        action: str,
    ) -> StatusResult:
        record = await self.repository.get_store(store_id, lock=True)
        if record is None or record.status is not source:
            # Release the row lock before answering.
            await self.session.rollback()
            if record is None:
                raise AdminStoreNotFound
            if record.status is target:
                return StatusResult(target, changed=False)
            raise StoreConflict

        async def change() -> None:
            await self.repository.set_status(store_id, target)

        await self._commit_audit(
            actor,
            record,
            action,
            before={"status": source.value},
            after={"status": target.value},
            change=change,
        )
        return StatusResult(target, changed=True)
