"""Admin re-run of store provisioning (KAN-200): FAILED -> PROVISIONING and re-enqueue."""

import pytest

from app.core.permissions import ADMIN_PERMISSIONS, AdminContext
from app.models.platform.store import StoreStatus
from app.services.admin_stores import (
    MAX_REPROVISION_ATTEMPTS,
    REPROVISION_ACTION,
    REPROVISION_FAILED_ACTION,
    AdminStoreNotFound,
    AdminStoresService,
    CommitFailed,
    ProvisioningNotStarted,
    RetryLimitReached,
    StoreConflict,
)
from tests.fakes_admin_stores import (
    FakeAuditor,
    FakeSession,
    FakeStoresRepository,
    store,
)

ADMIN = AdminContext("adm", "super_admin", ADMIN_PERMISSIONS)


class Starter:
    def __init__(self, repository: FakeStoresRepository, ok: bool = True) -> None:
        self.repository, self.ok = repository, ok
        self.calls: list[tuple[str, StoreStatus, int]] = []

    async def __call__(self, store_id: str, attempt: int) -> bool:
        # The status must already be committed as PROVISIONING when the job is enqueued.
        self.calls.append((store_id, self.repository.stores[store_id].status, attempt))
        return self.ok


def build(*stores, ok: bool = True):
    repository, session, auditor = (
        FakeStoresRepository(*stores),
        FakeSession(),
        FakeAuditor(),
    )
    starter = Starter(repository, ok)

    async def migrate(store_id: str) -> int:
        return 0

    service = AdminStoresService(
        repository, session, auditor, migrate, start_provisioning=starter
    )
    return service, repository, session, auditor, starter


async def test_failed_store_goes_back_to_provisioning_is_audited_and_enqueued():
    service, repository, session, auditor, starter = build(
        store("a", status=StoreStatus.FAILED, schema_version=0)
    )

    result = await service.reprovision(ADMIN, "a")

    assert (result.status, result.attempt) == (StoreStatus.PROVISIONING, 1)
    assert repository.stores["a"].status is StoreStatus.PROVISIONING
    assert repository.locked == ["a"]
    assert session.commits == 1
    assert starter.calls == [("a", StoreStatus.PROVISIONING, 1)]
    assert auditor.rows == [
        {
            "actor": "adm",
            "action": REPROVISION_ACTION,
            "resource": "stores",
            "resource_id": "a",
            "organization_id": "org1",
            "store_id": "a",
            "before": {"status": "FAILED"},
            "after": {"status": "PROVISIONING"},
            "details": {"attempt": 1, "max_attempts": MAX_REPROVISION_ATTEMPTS},
        }
    ]


@pytest.mark.parametrize(
    "status",
    [
        StoreStatus.PROVISIONING,
        StoreStatus.ACTIVE,
        StoreStatus.SUSPENDED,
        StoreStatus.ARCHIVED,
    ],
)
async def test_only_failed_stores_can_be_reprovisioned(status):
    service, repository, session, auditor, starter = build(store("a", status=status))

    with pytest.raises(StoreConflict):
        await service.reprovision(ADMIN, "a")

    assert repository.stores["a"].status is status
    assert (session.commits, session.rollbacks) == (0, 1)  # row lock released
    assert auditor.rows == [] and starter.calls == []


async def test_unknown_store_is_not_found():
    service, _repository, session, *_ = build()

    with pytest.raises(AdminStoreNotFound):
        await service.reprovision(ADMIN, "missing")

    assert (session.commits, session.rollbacks) == (0, 1)


async def test_attempt_number_continues_from_earlier_attempts():
    service, repository, *_, auditor, _ = build(store("a", status=StoreStatus.FAILED))
    repository.reprovisions["a"] = MAX_REPROVISION_ATTEMPTS - 1

    result = await service.reprovision(ADMIN, "a")

    assert result.attempt == MAX_REPROVISION_ATTEMPTS
    assert auditor.rows[0]["details"]["attempt"] == MAX_REPROVISION_ATTEMPTS


async def test_cap_reached_refuses_without_change_audit_or_enqueue():
    service, repository, session, auditor, starter = build(
        store("a", status=StoreStatus.FAILED)
    )
    repository.reprovisions["a"] = MAX_REPROVISION_ATTEMPTS

    with pytest.raises(RetryLimitReached):
        await service.reprovision(ADMIN, "a")

    assert repository.stores["a"].status is StoreStatus.FAILED
    assert (session.commits, session.rollbacks) == (0, 1)
    assert auditor.rows == [] and starter.calls == []


async def test_attempts_beyond_the_cap_also_refuse():
    service, repository, *_ = build(store("a", status=StoreStatus.FAILED))
    repository.reprovisions["a"] = MAX_REPROVISION_ATTEMPTS + 7

    with pytest.raises(RetryLimitReached):
        await service.reprovision(ADMIN, "a")


async def test_status_is_checked_before_the_cap():
    service, repository, *_ = build(store("a", status=StoreStatus.ACTIVE))
    repository.reprovisions["a"] = MAX_REPROVISION_ATTEMPTS

    with pytest.raises(StoreConflict):
        await service.reprovision(ADMIN, "a")


async def test_status_write_failure_is_a_commit_failure_without_enqueue():
    service, repository, session, auditor, starter = build(
        store("a", status=StoreStatus.FAILED)
    )

    async def broken(*args, **kwargs):
        raise RuntimeError("write failed")

    repository.set_status = broken

    with pytest.raises(CommitFailed):
        await service.reprovision(ADMIN, "a")

    assert repository.stores["a"].status is StoreStatus.FAILED
    assert (session.commits, session.rollbacks) == (0, 1)
    assert auditor.rows == [] and starter.calls == []


async def test_enqueue_failure_after_commit_raises_and_keeps_the_audit_row():
    service, _, session, auditor, starter = build(
        store("a", status=StoreStatus.FAILED), ok=False
    )

    with pytest.raises(ProvisioningNotStarted):
        await service.reprovision(ADMIN, "a")

    assert session.commits == 2  # the re-run, then the compensating row
    assert [row["action"] for row in auditor.rows] == [
        REPROVISION_ACTION,
        REPROVISION_FAILED_ACTION,
    ]
    assert len(starter.calls) == 1


async def test_audit_failure_rolls_back_and_never_enqueues():
    service, _repository, session, auditor, starter = build(
        store("a", status=StoreStatus.FAILED)
    )

    async def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    auditor.record = broken

    with pytest.raises(CommitFailed):
        await service.reprovision(ADMIN, "a")

    assert session.commits == 0 and session.rollbacks == 1
    assert starter.calls == []
