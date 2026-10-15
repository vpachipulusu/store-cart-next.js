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
from app.services.store_migrations import StoreMigrationFailed, StoreVersionNotRecorded

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
    """The result could not be recorded after the store was migrated (503, retry)."""


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
        store: StoresStore,
        session: AsyncSession,
        auditor: AuditRecorder,
        migrate: Callable[[str], Awaitable[int]],
        timeout: float = MIGRATE_TIMEOUT_SECONDS,
    ) -> None:
        self.store, self.session, self.auditor = store, session, auditor
        self.migrate_store, self.timeout = migrate, timeout

    async def list_organizations(
        self, search: str | None, limit: int, offset: int
    ) -> OrganizationPage:
        return await self.store.list_organizations(
            search, min(max(limit, 1), MAX_PAGE_SIZE), max(offset, 0)
        )

    async def list_stores(
        self, filters: StoreFilters, limit: int, offset: int
    ) -> StorePage:
        return await self.store.list_stores(
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
        record = await self.store.get_store(store_id)
        if record is None:
            raise AdminStoreNotFound
        if record.status not in MIGRATABLE_STATUSES or store_id in _migrating:
            raise StoreConflict
        # End the read transaction: no connection is held while the store is migrated.
        await self.session.rollback()
        _migrating.add(store_id)
        try:
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
        return MigrateResult(record.schema_version, version)

    async def _run_migration(self, actor: AdminContext, record: StoreRecord) -> int:
        try:
            return await asyncio.wait_for(self.migrate_store(record.id), self.timeout)
        except StoreVersionNotRecorded as failure:
            reason = f"version not recorded (re-run to repair): {failure.reason}"
            await self._record(actor, record, MIGRATE_FAILED_ACTION, reason=reason)
            raise MigrationFailed from None
        except StoreMigrationFailed as failure:
            await self._record(
                actor, record, MIGRATE_FAILED_ACTION, reason=failure.reason
            )
            raise MigrationFailed from None
        except TimeoutError:
            await self._record(
                actor, record, MIGRATE_FAILED_ACTION, reason=TIMEOUT_REASON
            )
            raise MigrationTimeout from None

    async def _record(
        self,
        actor: AdminContext,
        record: StoreRecord,
        action: str,
        *,
        before: object = None,
        after: object = None,
        reason: str | None = None,
    ) -> None:
        """Audit a migration outcome in its own transaction (the migration is idempotent,
        so a failure here is a 503 telling the admin to retry)."""
        try:
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
        except Exception:
            logger.exception(
                "admin store migration outcome was not audited",
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
        record = await self.store.get_store(store_id, lock=True)
        if record is None:
            raise AdminStoreNotFound
        if record.status is target:
            return StatusResult(target, changed=False)
        if record.status is not source:
            raise StoreConflict
        await self.store.set_status(store_id, target)
        await self.auditor.record(
            actor,
            action=action,
            resource="stores",
            resource_id=record.id,
            organization_id=record.organization_id,
            store_id=record.id,
            before={"status": source.value},
            after={"status": target.value},
        )
        await self.session.commit()
        return StatusResult(target, changed=True)
