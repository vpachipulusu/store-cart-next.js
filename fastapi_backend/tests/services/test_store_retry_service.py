"""Merchant retry through the shared re-run service (KAN-242), with in-memory doubles."""

import pytest

from app.core.permissions import AdminContext
from app.models.platform.store import StoreStatus
from app.services.admin_stores import (
    MERCHANT_RETRY,
    AdminStoresService,
    CommitFailed,
    ProvisioningNotStarted,
    StoreConflict,
)
from tests.fakes_admin_stores import (
    FakeAuditor,
    FakeSession,
    FakeStoresRepository,
    store,
)

MERCHANT = AdminContext("usr-1", "OWNER", frozenset())


def build(repository: FakeStoresRepository, *, enqueued: bool = True):
    session, auditor = FakeSession(), FakeAuditor()
    started: list[tuple[str, int]] = []

    async def start(store_id: str, attempt: int) -> bool:
        started.append((store_id, attempt))
        return enqueued

    async def migrate(store_id: str) -> int:
        return 0

    service = AdminStoresService(
        repository, session, auditor, migrate, start_provisioning=start
    )
    return service, session, auditor, started


async def test_a_merchant_retry_audits_under_the_merchant_actions():
    repository = FakeStoresRepository(store("s1", status=StoreStatus.FAILED))
    service, _session, auditor, started = build(repository)

    result = await service.reprovision(MERCHANT, "s1", MERCHANT_RETRY)

    assert (result.status, result.attempt) == (StoreStatus.PROVISIONING, 1)
    assert [(r["actor"], r["action"]) for r in auditor.rows] == [
        ("usr-1", "stores.retry_provisioning")
    ]
    assert started == [("s1", 1)]


async def test_a_failed_enqueue_audits_the_merchant_failure_action():
    repository = FakeStoresRepository(store("s1", status=StoreStatus.FAILED))
    service, _session, auditor, _started = build(repository, enqueued=False)

    with pytest.raises(ProvisioningNotStarted):
        await service.reprovision(MERCHANT, "s1", MERCHANT_RETRY)

    assert [r["action"] for r in auditor.rows] == [
        "stores.retry_provisioning",
        "stores.retry_provisioning_failed",
    ]
    assert repository.stores["s1"].status is StoreStatus.FAILED


async def test_losing_the_conditional_update_is_a_conflict_that_queues_nothing():
    repository = FakeStoresRepository(store("s1", status=StoreStatus.FAILED))
    service, session, auditor, started = build(repository)

    async def lose_the_race(store_id: str) -> bool:
        return False  # another request flipped the status between read and update

    repository.claim_failed = lose_the_race  # type: ignore[method-assign]

    with pytest.raises(StoreConflict):
        await service.reprovision(MERCHANT, "s1", MERCHANT_RETRY)

    assert (started, auditor.rows, session.commits) == ([], [], 0)
    assert session.rollbacks >= 1


async def test_compensation_leaves_a_store_the_job_already_moved_on():
    repository = FakeStoresRepository(store("s1", status=StoreStatus.FAILED))
    session, auditor = FakeSession(), FakeAuditor()

    async def start(store_id: str, attempt: int) -> bool:
        # The job got going (and finished) before the enqueue reported a failure.
        await repository.set_status(store_id, StoreStatus.ACTIVE)
        return False

    async def migrate(store_id: str) -> int:
        return 0

    service = AdminStoresService(
        repository, session, auditor, migrate, start_provisioning=start
    )

    with pytest.raises(ProvisioningNotStarted):
        await service.reprovision(MERCHANT, "s1", MERCHANT_RETRY)

    assert repository.stores["s1"].status is StoreStatus.ACTIVE
    assert [r["action"] for r in auditor.rows] == ["stores.retry_provisioning"]
    assert session.commits == 1  # only the claim; nothing was written to compensate


async def test_a_failed_compensation_commit_is_logged_at_error_with_the_store_id(
    caplog,
):
    class CommitFailsSecondTime(FakeSession):
        async def commit(self) -> None:
            await super().commit()
            if self.commits > 1:
                raise RuntimeError("connection lost")

    repository = FakeStoresRepository(store("s1", status=StoreStatus.FAILED))
    session, auditor = CommitFailsSecondTime(), FakeAuditor()

    async def start(store_id: str, attempt: int) -> bool:
        return False

    async def migrate(store_id: str) -> int:
        return 0

    service = AdminStoresService(
        repository, session, auditor, migrate, start_provisioning=start
    )

    with (
        caplog.at_level("ERROR", logger="storecart.admin_stores"),
        pytest.raises(CommitFailed),
    ):
        await service.reprovision(MERCHANT, "s1", MERCHANT_RETRY)

    stranded = [
        r
        for r in caplog.records
        if r.levelname == "ERROR" and getattr(r, "store_id", None) == "s1"
    ]
    assert any("compensation" in r.getMessage() for r in stranded)
