import asyncio

import pytest

from app.core.permissions import ADMIN_PERMISSIONS, AdminContext
from app.models.platform.store import StoreStatus
from app.repositories.admin_stores import StoreFilters
from app.services.admin_stores import (
    MAX_PAGE_SIZE,
    TIMEOUT_REASON,
    AdminStoreNotFound,
    AdminStoresService,
    CommitFailed,
    MigrationFailed,
    MigrationTimeout,
    StoreConflict,
)
from app.services.store_migrations import StoreMigrationFailed, StoreVersionNotRecorded
from tests.fakes_admin_stores import (
    FakeAuditor,
    FakeSession,
    FakeStoresRepository,
    store,
)

ADMIN = AdminContext("adm", "super_admin", ADMIN_PERMISSIONS)
NO_FILTER = StoreFilters(None, None, None)


class Migrator:
    def __init__(self, version: int = 3) -> None:
        self.version = version
        self.calls: list[str] = []
        self.failure: Exception | None = None
        self.delay = 0.0

    async def __call__(self, store_id: str) -> int:
        self.calls.append(store_id)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure
        return self.version


def build(*stores, timeout: float = 5.0):
    repository, session, auditor, migrator = (
        FakeStoresRepository(*stores),
        FakeSession(),
        FakeAuditor(),
        Migrator(),
    )
    service = AdminStoresService(repository, session, auditor, migrator, timeout)
    return service, repository, session, auditor, migrator


async def test_list_caps_page_size_and_floors_offset():
    service, repository, *_ = build(store("a"))

    await service.list_stores(NO_FILTER, 10_000, -4)

    assert repository.list_calls == [("stores", NO_FILTER, MAX_PAGE_SIZE, 0)]


async def test_list_organizations_floors_page_size_at_one():
    service, repository, *_ = build(store("a"))

    await service.list_organizations(None, 0, 0)

    assert repository.list_calls == [("orgs", None, 1, 0)]


async def test_suspend_active_store_sets_status_and_audits_in_same_commit():
    service, repository, session, auditor, _ = build(store("a"))

    result = await service.suspend(ADMIN, "a")

    assert result.changed is True
    assert repository.stores["a"].status is StoreStatus.SUSPENDED
    assert repository.locked == ["a"]
    assert session.commits == 1
    assert auditor.rows == [
        {
            "actor": "adm",
            "action": "admin.stores.suspend",
            "resource": "stores",
            "resource_id": "a",
            "organization_id": "org1",
            "store_id": "a",
            "before": {"status": "ACTIVE"},
            "after": {"status": "SUSPENDED"},
        }
    ]


async def test_suspend_already_suspended_is_a_no_op_without_audit():
    service, _, session, auditor, _ = build(store("a", status=StoreStatus.SUSPENDED))

    result = await service.suspend(ADMIN, "a")

    assert result.changed is False
    assert session.commits == 0
    assert auditor.rows == []


@pytest.mark.parametrize("status", [StoreStatus.PROVISIONING, StoreStatus.ARCHIVED])
async def test_suspend_refuses_stores_that_are_not_live(status):
    service, repository, session, auditor, _ = build(store("a", status=status))

    with pytest.raises(StoreConflict):
        await service.suspend(ADMIN, "a")

    assert repository.stores["a"].status is status
    assert session.commits == 0
    assert auditor.rows == []


async def test_unsuspend_restores_active_and_audits():
    service, repository, _, auditor, _ = build(store("a", status=StoreStatus.SUSPENDED))

    result = await service.unsuspend(ADMIN, "a")

    assert result.changed is True
    assert repository.stores["a"].status is StoreStatus.ACTIVE
    assert auditor.rows[0]["action"] == "admin.stores.unsuspend"
    assert auditor.rows[0]["before"] == {"status": "SUSPENDED"}


@pytest.mark.parametrize("status", [StoreStatus.PROVISIONING, StoreStatus.ARCHIVED])
async def test_unsuspend_refuses_other_states(status):
    service, *_ = build(store("a", status=status))

    with pytest.raises(StoreConflict):
        await service.unsuspend(ADMIN, "a")


async def test_unsuspend_active_store_is_a_no_op():
    service, _, session, auditor, _ = build(store("a"))

    result = await service.unsuspend(ADMIN, "a")

    assert result.changed is False
    assert auditor.rows == []
    assert session.commits == 0


@pytest.mark.parametrize("action", ["suspend", "unsuspend", "migrate"])
async def test_unknown_store_is_not_found(action):
    service, *_ = build()

    with pytest.raises(AdminStoreNotFound):
        await getattr(service, action)(ADMIN, "missing")


@pytest.mark.parametrize("status", [StoreStatus.ACTIVE, StoreStatus.SUSPENDED])
async def test_migrate_runs_the_migration_and_audits_the_version_change(status):
    service, _, session, auditor, migrator = build(
        store("a", status=status, schema_version=1)
    )

    result = await service.migrate(ADMIN, "a")

    assert (result.previous_version, result.schema_version) == (1, 3)
    assert migrator.calls == ["a"]
    assert session.rollbacks == 1  # no transaction is held while migrating
    assert session.commits == 1
    assert auditor.rows == [
        {
            "actor": "adm",
            "action": "admin.stores.migrate",
            "resource": "stores",
            "resource_id": "a",
            "organization_id": "org1",
            "store_id": "a",
            "before": {"schema_version": 1},
            "after": {"schema_version": 3},
            "details": None,
        }
    ]


@pytest.mark.parametrize("status", [StoreStatus.PROVISIONING, StoreStatus.ARCHIVED])
async def test_migrate_refuses_provisioning_and_archived_stores(status):
    service, _, _, auditor, migrator = build(store("a", status=status))

    with pytest.raises(StoreConflict):
        await service.migrate(ADMIN, "a")

    assert migrator.calls == []
    assert auditor.rows == []


async def test_failed_migration_is_audited_with_a_safe_reason_and_raises():
    service, _, session, auditor, migrator = build(store("a"))
    migrator.failure = StoreMigrationFailed("a", "OperationalError sqlstate=08006")

    with pytest.raises(MigrationFailed):
        await service.migrate(ADMIN, "a")

    assert session.commits == 1
    assert auditor.rows[0]["action"] == "admin.stores.migrate_failed"
    assert auditor.rows[0]["details"] == {"reason": "OperationalError sqlstate=08006"}


async def test_slow_migration_times_out_and_is_audited():
    service, _, session, auditor, migrator = build(store("a"), timeout=0.01)
    migrator.delay = 1.0

    with pytest.raises(MigrationTimeout):
        await service.migrate(ADMIN, "a")

    assert auditor.rows[0]["action"] == "admin.stores.migrate_failed"
    assert auditor.rows[0]["details"] == {"reason": TIMEOUT_REASON}
    assert session.commits == 1


async def test_version_not_recorded_is_audited_as_repairable():
    service, _, _, auditor, migrator = build(store("a"))
    migrator.failure = StoreVersionNotRecorded("a", "OperationalError")

    with pytest.raises(MigrationFailed):
        await service.migrate(ADMIN, "a")

    reason = auditor.rows[0]["details"]["reason"]
    assert reason.startswith("version not recorded (re-run to repair)")


async def test_audit_failure_after_a_migration_is_a_retryable_commit_failure():
    service, _, session, auditor, _ = build(store("a"))

    async def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    auditor.record = broken

    with pytest.raises(CommitFailed):
        await service.migrate(ADMIN, "a")

    assert session.rollbacks == 2  # before the migration, and after the failed audit


async def test_second_concurrent_migration_of_the_same_store_is_a_conflict():
    service, _, _, auditor, migrator = build(store("a"))
    migrator.delay = 0.05

    first = asyncio.create_task(service.migrate(ADMIN, "a"))
    await asyncio.sleep(0.01)
    with pytest.raises(StoreConflict):
        await service.migrate(ADMIN, "a")
    await first

    assert migrator.calls == ["a"]
    assert len(auditor.rows) == 1
    await service.migrate(ADMIN, "a")  # free again once the first one ended
