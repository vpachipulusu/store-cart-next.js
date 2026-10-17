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
    no_start,
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
    service = AdminStoresService(
        repository, session, auditor, migrator, timeout, start_provisioning=no_start
    )
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
            "details": None,
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
    service, _, _, auditor, _ = build(store("a"))
    gated = GatedMigrator()
    service._migrate = gated

    first = asyncio.create_task(service.migrate(ADMIN, "a"))
    try:
        async with asyncio.timeout(5):
            await gated.started.wait()
            with pytest.raises(StoreConflict):
                await service.migrate(ADMIN, "a")
    finally:
        gated.release.set()  # a failure above must not leave the first task hanging
    async with asyncio.timeout(5):
        await first

    assert gated.calls == ["a"]
    assert len(auditor.rows) == 1
    await service.migrate(ADMIN, "a")  # free again once the first one ended


class YieldingSession(FakeSession):
    """A session whose rollback gives other tasks a chance to run, like real I/O."""

    async def rollback(self) -> None:
        await asyncio.sleep(0)
        await super().rollback()


async def test_concurrent_migrations_of_one_store_yield_exactly_one_conflict():
    service, _, _, auditor, migrator = build(store("a"))
    service.session = YieldingSession()
    migrator.delay = 0.05

    outcomes = await asyncio.gather(
        service.migrate(ADMIN, "a"),
        service.migrate(ADMIN, "a"),
        return_exceptions=True,
    )

    conflicts = [o for o in outcomes if isinstance(o, StoreConflict)]
    assert len(conflicts) == 1
    assert sum(not isinstance(o, Exception) for o in outcomes) == 1
    assert migrator.calls == ["a"]
    assert len(auditor.rows) == 1


async def test_claim_is_released_when_ending_the_read_transaction_fails():
    service, _, session, _, _ = build(store("a"))

    async def broken_rollback() -> None:
        raise RuntimeError("pool down")

    session.rollback = broken_rollback

    with pytest.raises(CommitFailed):  # the documented 503, not a raw 500
        await service.migrate(ADMIN, "a")

    session.rollback = FakeSession().rollback
    await service.migrate(ADMIN, "a")  # not stuck behind a stale claim


async def test_unexpected_migration_error_is_audited_with_a_safe_reason_and_raises():
    service, _, session, auditor, migrator = build(store("a"))
    migrator.failure = RuntimeError("postgres://user:secret@host/db")

    with pytest.raises(MigrationFailed):
        await service.migrate(ADMIN, "a")

    assert session.commits == 1
    assert auditor.rows[0]["action"] == "admin.stores.migrate_failed"
    assert auditor.rows[0]["details"] == {"reason": "RuntimeError"}
    assert "secret" not in repr(auditor.rows)


async def test_timeout_error_raised_by_the_migration_is_not_reported_as_a_timeout():
    service, _, _, auditor, migrator = build(store("a"))
    migrator.failure = TimeoutError("driver gave up")

    with pytest.raises(MigrationFailed):
        await service.migrate(ADMIN, "a")

    assert auditor.rows[0]["details"] == {"reason": "TimeoutError"}


async def test_unexpected_error_whose_audit_write_fails_is_a_commit_failure():
    service, _, _, auditor, migrator = build(store("a"))
    migrator.failure = RuntimeError("boom")

    async def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    auditor.record = broken

    with pytest.raises(CommitFailed):
        await service.migrate(ADMIN, "a")


@pytest.mark.parametrize("action", ["suspend", "unsuspend"])
async def test_not_found_releases_the_row_lock(action):
    service, _, session, _, _ = build()

    with pytest.raises(AdminStoreNotFound):
        await getattr(service, action)(ADMIN, "missing")

    assert (session.rollbacks, session.commits) == (1, 0)


@pytest.mark.parametrize(
    ("action", "status"),
    [("suspend", StoreStatus.SUSPENDED), ("unsuspend", StoreStatus.ACTIVE)],
)
async def test_no_op_releases_the_row_lock(action, status):
    service, _, session, _, _ = build(store("a", status=status))

    await getattr(service, action)(ADMIN, "a")

    assert (session.rollbacks, session.commits) == (1, 0)


async def test_conflict_releases_the_row_lock():
    service, _, session, _, _ = build(store("a", status=StoreStatus.ARCHIVED))

    with pytest.raises(StoreConflict):
        await service.suspend(ADMIN, "a")

    assert (session.rollbacks, session.commits) == (1, 0)


@pytest.mark.parametrize("action", ["suspend", "unsuspend"])
async def test_status_change_whose_audit_write_fails_is_rolled_back_as_503(action):
    status = StoreStatus.ACTIVE if action == "suspend" else StoreStatus.SUSPENDED
    service, _, session, auditor, _ = build(store("a", status=status))

    async def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    auditor.record = broken

    with pytest.raises(CommitFailed):
        await getattr(service, action)(ADMIN, "a")

    assert (session.rollbacks, session.commits) == (1, 0)


async def test_status_change_whose_commit_fails_is_rolled_back_as_503():
    service, _, session, _, _ = build(store("a"))

    async def broken_commit() -> None:
        raise RuntimeError("connection lost")

    session.commit = broken_commit

    with pytest.raises(CommitFailed):
        await service.suspend(ADMIN, "a")

    assert session.rollbacks == 1


@pytest.fixture(autouse=True)
def _no_leftover_claims():
    from app.services import admin_stores

    admin_stores._migrating.clear()
    yield
    assert admin_stores._migrating == set()  # every test released its claims
    admin_stores._migrating.clear()


class GatedMigrator(Migrator):
    """Signals when it has started, then waits until released."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, store_id: str) -> int:
        self.calls.append(store_id)
        self.started.set()
        await self.release.wait()
        return self.version


async def test_cancelled_request_writes_no_audit_row_and_releases_the_claim():
    service, _, session, auditor, _ = build(store("a"))
    gated = GatedMigrator()
    service._migrate = gated

    task = asyncio.create_task(service.migrate(ADMIN, "a"))
    await gated.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert auditor.rows == []
    assert session.commits == 0
    service._migrate = Migrator()
    await service.migrate(ADMIN, "a")  # the claim is free again


async def test_other_stores_can_migrate_while_one_is_running():
    service, _, _, auditor, _ = build(store("a"), store("b"))
    gated = GatedMigrator()
    service._migrate = gated

    first = asyncio.create_task(service.migrate(ADMIN, "a"))
    await gated.started.wait()
    service._migrate = Migrator()
    await service.migrate(ADMIN, "b")  # a different store is not blocked
    gated.release.set()
    await first

    assert [row["store_id"] for row in auditor.rows] == ["b", "a"]


@pytest.mark.parametrize(
    "failure",
    [
        StoreMigrationFailed("a", "OperationalError sqlstate=08006"),
        RuntimeError("boom"),
    ],
)
async def test_claim_is_released_after_a_failed_migration(failure):
    service, _, _, _, migrator = build(store("a"))
    migrator.failure = failure
    with pytest.raises(MigrationFailed):
        await service.migrate(ADMIN, "a")

    migrator.failure = None
    await service.migrate(ADMIN, "a")  # not a StoreConflict


async def test_claim_is_released_after_a_timeout():
    service, _, _, _, migrator = build(store("a"), timeout=0.01)
    migrator.delay = 1.0
    with pytest.raises(MigrationTimeout):
        await service.migrate(ADMIN, "a")

    migrator.delay = 0.0
    service.timeout = 5.0
    await service.migrate(ADMIN, "a")


@pytest.mark.parametrize("action", ["suspend", "unsuspend"])
@pytest.mark.parametrize("status", [StoreStatus.PROVISIONING, StoreStatus.ARCHIVED])
async def test_conflicting_status_releases_the_row_lock_for_both_actions(
    action, status
):
    service, _, session, _, _ = build(store("a", status=status))

    with pytest.raises(StoreConflict):
        await getattr(service, action)(ADMIN, "a")

    assert (session.rollbacks, session.commits) == (1, 0)


async def test_unknown_or_conflicting_migrate_ends_the_read_transaction():
    service, _, session, _, _ = build(store("a", status=StoreStatus.ARCHIVED))

    with pytest.raises(StoreConflict):
        await service.migrate(ADMIN, "a")
    with pytest.raises(AdminStoreNotFound):
        await service.migrate(ADMIN, "missing")

    assert session.rollbacks == 2


async def test_unexpected_error_is_raised_without_a_cause_chain():
    service, _, _, _, migrator = build(store("a"))
    migrator.failure = RuntimeError("postgres://user:secret@host/db")

    with pytest.raises(MigrationFailed) as raised:
        await service.migrate(ADMIN, "a")

    assert raised.value.__cause__ is None and raised.value.__suppress_context__


async def test_migration_start_and_finish_are_logged_with_store_and_admin(caplog):
    service, *_ = build(store("a"))

    with caplog.at_level("INFO", logger="storecart.admin_stores"):
        await service.migrate(ADMIN, "a")

    started, finished = [
        r for r in caplog.records if r.name == "storecart.admin_stores"
    ]
    assert started.getMessage() == "admin store migration started"
    assert (started.store_id, started.admin_user_id) == ("a", "adm")
    assert finished.getMessage() == "admin store migration finished"
    assert finished.schema_version == 3


async def test_failing_rollback_after_a_failed_audit_write_is_still_a_503():
    service, _, session, auditor, _ = build(store("a"))

    async def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    async def broken_rollback() -> None:
        raise RuntimeError("connection lost")

    auditor.record = broken
    session.rollback = broken_rollback

    with pytest.raises(CommitFailed):
        await service.suspend(ADMIN, "a")


async def test_failing_rollback_does_not_hide_a_conflict_or_a_no_op():
    service, _, session, _, _ = build(
        store("a", status=StoreStatus.ARCHIVED), store("b")
    )

    async def broken_rollback() -> None:
        raise RuntimeError("connection lost")

    session.rollback = broken_rollback

    with pytest.raises(StoreConflict):
        await service.suspend(ADMIN, "a")
    with pytest.raises(AdminStoreNotFound):
        await service.suspend(ADMIN, "missing")
    assert (await service.unsuspend(ADMIN, "b")).changed is False
