"""In-memory doubles for the admin stores repository and audit recorder."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.core.permissions import AdminContext
from app.models.platform.store import StoreStatus
from app.repositories.admin_stores import (
    OrganizationPage,
    OrganizationRecord,
    ReprovisionCounts,
    StoreFilters,
    StorePage,
    StoreRecord,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def store(
    store_id: str,
    *,
    status: StoreStatus = StoreStatus.ACTIVE,
    schema_version: int = 1,
    organization_id: str = "org1",
) -> StoreRecord:
    return StoreRecord(
        id=store_id,
        organization_id=organization_id,
        organization_name=organization_id.title(),
        name=store_id.title(),
        slug=store_id,
        status=status,
        schema_version=schema_version,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeStoresRepository:
    def __init__(self, *stores: StoreRecord) -> None:
        self.stores = {s.id: s for s in stores}
        self.locked: list[str] = []
        self.list_calls: list[tuple[Any, ...]] = []
        self.reprovisions: dict[str, int] = {}
        self.reprovision_failures: dict[str, int] = {}

    async def count_reprovisions(self, store_id: str) -> ReprovisionCounts:
        return ReprovisionCounts(
            self.reprovisions.get(store_id, 0),
            self.reprovision_failures.get(store_id, 0),
        )

    async def list_organizations(
        self, search: str | None, limit: int, offset: int
    ) -> OrganizationPage:
        self.list_calls.append(("orgs", search, limit, offset))
        orgs = {
            s.organization_id: OrganizationRecord(
                s.organization_id, s.organization_name, s.organization_id, 1, NOW
            )
            for s in self.stores.values()
        }
        rows = list(orgs.values())
        return OrganizationPage(rows[offset : offset + limit], len(rows))

    async def list_stores(
        self, filters: StoreFilters, limit: int, offset: int
    ) -> StorePage:
        self.list_calls.append(("stores", filters, limit, offset))
        rows = [
            s
            for s in self.stores.values()
            if (filters.status is None or s.status == filters.status)
            and (
                filters.organization_id is None
                or s.organization_id == filters.organization_id
            )
        ]
        return StorePage(rows[offset : offset + limit], len(rows))

    async def get_store(
        self, store_id: str, *, lock: bool = False
    ) -> StoreRecord | None:
        if lock:
            self.locked.append(store_id)
        return self.stores.get(store_id)

    async def set_status(self, store_id: str, status: StoreStatus) -> None:
        self.stores[store_id] = replace(self.stores[store_id], status=status)

    async def claim_failed(self, store_id: str) -> bool:
        if self.stores[store_id].status is not StoreStatus.FAILED:
            return False
        await self.set_status(store_id, StoreStatus.PROVISIONING)
        return True


class FakeAuditor:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def record(self, admin: AdminContext, **fields: Any) -> None:
        self.rows.append({"actor": admin.user_id, **fields})


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def no_start(store_id: str, attempt: int) -> bool:
    raise AssertionError("provisioning must not start")
