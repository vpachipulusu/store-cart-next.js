"""Queries behind the admin organisations and stores API (KAN-201). No business rules here.

``store_count`` counts every store row of the organisation, whatever its status.
Rows never carry ``database_ref`` or ``connection_string_encrypted``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select, update

from app.models.platform.audit_log import AuditLog
from app.models.platform.organization import Organization
from app.models.platform.store import Store, StoreStatus
from app.repositories.base import BaseRepository

REPROVISION_ACTION = "admin.stores.reprovision"
REPROVISION_FAILED_ACTION = "admin.stores.reprovision_failed"
# The merchant's own retry (KAN-242) writes its own actions; the cap counts both families.
MERCHANT_RETRY_ACTION = "stores.retry_provisioning"
MERCHANT_RETRY_FAILED_ACTION = "stores.retry_provisioning_failed"
_STARTED_ACTIONS = (REPROVISION_ACTION, MERCHANT_RETRY_ACTION)
_FAILED_ACTIONS = (REPROVISION_FAILED_ACTION, MERCHANT_RETRY_FAILED_ACTION)


@dataclass(frozen=True)
class OrganizationRecord:
    id: str
    name: str
    slug: str
    store_count: int
    created_at: datetime


@dataclass(frozen=True)
class OrganizationPage:
    items: list[OrganizationRecord]
    total_count: int


@dataclass(frozen=True)
class StoreFilters:
    status: StoreStatus | None
    organization_id: str | None
    search: str | None


@dataclass(frozen=True)
class StoreRecord:
    id: str
    organization_id: str
    organization_name: str
    name: str
    slug: str
    status: StoreStatus
    schema_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ReprovisionCounts:
    started: int
    failed: int


@dataclass(frozen=True)
class StorePage:
    items: list[StoreRecord]
    total_count: int


StoreSelect = Select[str, str, str, str, str, StoreStatus, int, datetime, datetime]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _organization_match(search: str | None) -> list[ColumnElement[bool]]:
    if not search:
        return []
    pattern = f"%{_escape_like(search)}%"
    return [
        Organization.name.ilike(pattern, escape="\\")
        | Organization.slug.ilike(pattern, escape="\\")
    ]


def organizations_statement(
    match: list[ColumnElement[bool]], limit: int, offset: int
) -> Select[Any]:
    """One page of organisations, then the store count for those rows only.

    Paging happens first (newest first, id as tie-break), so the count never aggregates
    stores of organisations that are not on the page.
    """
    page = (
        select(
            Organization.id,
            Organization.name,
            Organization.slug,
            Organization.created_at,
        )
        .where(*match)
        .order_by(Organization.created_at.desc(), Organization.id)
        .limit(limit)
        .offset(offset)
        .subquery("page")
    )
    store_count = (
        select(func.count(Store.id))
        .where(Store.organization_id == page.c.id)
        .scalar_subquery()
    )
    return select(
        page.c.id, page.c.name, page.c.slug, store_count, page.c.created_at
    ).order_by(page.c.created_at.desc(), page.c.id)


def _select_stores() -> StoreSelect:
    return select(
        Store.id,
        Store.organization_id,
        Organization.name,
        Store.name,
        Store.slug,
        Store.status,
        Store.schema_version,
        Store.created_at,
        Store.updated_at,
    ).join(Organization, Organization.id == Store.organization_id)


class AdminStoresRepository(BaseRepository):
    async def list_organizations(
        self, search: str | None, limit: int, offset: int
    ) -> OrganizationPage:
        match = _organization_match(search)
        statement = organizations_statement(match, limit, offset)
        count = select(func.count()).select_from(Organization).where(*match)
        rows = (await self._session.execute(statement)).all()
        total = (await self._session.execute(count)).scalar_one()
        return OrganizationPage([OrganizationRecord(*row) for row in rows], total)

    async def list_stores(
        self, filters: StoreFilters, limit: int, offset: int
    ) -> StorePage:
        conditions = []
        if filters.status is not None:
            conditions.append(Store.status == filters.status)
        if filters.organization_id is not None:
            conditions.append(Store.organization_id == filters.organization_id)
        if filters.search:
            pattern = f"%{_escape_like(filters.search)}%"
            conditions.append(
                Store.name.ilike(pattern, escape="\\")
                | Store.slug.ilike(pattern, escape="\\")
            )
        statement = (
            _select_stores()
            .where(*conditions)
            .order_by(Store.created_at.desc(), Store.id)
            .limit(limit)
            .offset(offset)
        )
        count = select(func.count()).select_from(Store).where(*conditions)
        rows = (await self._session.execute(statement)).all()
        total = (await self._session.execute(count)).scalar_one()
        return StorePage([StoreRecord(*row) for row in rows], total)

    async def get_store(
        self, store_id: str, *, lock: bool = False
    ) -> StoreRecord | None:
        if lock:
            # Lock first, then read in a fresh statement, so the status read is the
            # one that holds after any lock wait.
            await self._session.execute(
                select(Store.id).where(Store.id == store_id).with_for_update()
            )
        row = (
            await self._session.execute(_select_stores().where(Store.id == store_id))
        ).one_or_none()
        return StoreRecord(*row) if row is not None else None

    async def set_status(self, store_id: str, status: StoreStatus) -> None:
        await self._session.execute(
            update(Store).where(Store.id == store_id).values(status=status)
        )

    async def claim_failed(self, store_id: str) -> bool:
        """FAILED to PROVISIONING in one conditional UPDATE; False when it was not FAILED.

        Of two concurrent callers exactly one gets True, so only one chain is queued.
        """
        result = await self._session.execute(
            update(Store)
            .where(Store.id == store_id, Store.status == StoreStatus.FAILED)
            .values(status=StoreStatus.PROVISIONING)
            .returning(Store.id)
        )
        return result.first() is not None

    async def release_provisioning(self, store_id: str) -> StoreStatus | None:
        """PROVISIONING to FAILED in one conditional UPDATE (the enqueue compensation).

        Returns the status the store has afterwards: FAILED when this update did it or
        when it was already FAILED (``start_provisioning`` marks it itself), anything
        else when the job already moved it on, and that outcome is not overwritten.
        None when the store no longer exists.
        """
        result = await self._session.execute(
            update(Store)
            .where(Store.id == store_id, Store.status == StoreStatus.PROVISIONING)
            .values(status=StoreStatus.FAILED)
            .returning(Store.id)
        )
        if result.first() is not None:
            return StoreStatus.FAILED
        current = await self._session.execute(
            select(Store.status).where(Store.id == store_id)
        )
        return current.scalar_one_or_none()

    async def count_reprovisions(self, store_id: str) -> ReprovisionCounts:
        """Audited re-runs of the store (admin or merchant) and how many failed to enqueue.

        ``started`` only grows, so ``started + 1`` is a monotonic attempt number; the
        retry cap uses ``started - failed``. This relies on audit rows being retained:
        any future audit purge must keep ``admin.stores.reprovision*`` and
        ``stores.retry_provisioning*`` rows.
        """
        started = func.count(AuditLog.id).filter(AuditLog.action.in_(_STARTED_ACTIONS))
        failed = func.count(AuditLog.id).filter(AuditLog.action.in_(_FAILED_ACTIONS))
        row = (
            await self._session.execute(
                select(started, failed).where(
                    AuditLog.store_id == store_id,
                    AuditLog.action.in_(_STARTED_ACTIONS + _FAILED_ACTIONS),
                )
            )
        ).one()
        return ReprovisionCounts(started=row[0], failed=row[1])
