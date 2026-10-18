"""Stores stuck in PROVISIONING: list them and mark them FAILED (KAN-248)."""

from datetime import timedelta

import pytest

from app.api.v1.admin_stores import get_admin_stores_service
from app.models.platform.store import StoreStatus
from app.services.admin_stores import STUCK_AFTER, AdminStoresService
from tests.api.test_admin_stores import Harness
from tests.fakes_admin_stores import NOW, no_start, store


class StuckHarness(Harness):
    def __init__(self, age: timedelta) -> None:
        super().__init__()
        self.grants["reprovisioner"] = ("admin", ["stores.reprovision"])

        async def migrate(store_id: str) -> int:
            return 0

        self.app.dependency_overrides[get_admin_stores_service] = lambda: (
            AdminStoresService(
                self.repository,
                self.session,
                self.auditor,
                migrate,
                start_provisioning=no_start,
                clock=lambda: NOW + age,
            )
        )


@pytest.fixture
def stuck() -> StuckHarness:
    return StuckHarness(STUCK_AFTER + timedelta(minutes=1))


@pytest.fixture
def fresh() -> StuckHarness:
    return StuckHarness(STUCK_AFTER - timedelta(minutes=1))


async def test_lists_stores_provisioning_longer_than_the_threshold(stuck):
    async with stuck.client("reader") as client:
        result = await client.get("/v1/admin/stores/stuck")

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    body = result.json()["data"]
    assert [s["id"] for s in body["stores"]] == ["new"]
    assert body["stuck_after_minutes"] == 15
    assert body["truncated"] is False
    assert body["stores"][0]["minutes_stuck"] == 16
    assert "database_ref" not in str(body)


async def test_does_not_list_a_store_that_is_still_within_the_threshold(fresh):
    async with fresh.client("reader") as client:
        result = await client.get("/v1/admin/stores/stuck")

    assert result.json()["data"]["stores"] == []


async def test_listing_needs_stores_read(stuck):
    async with stuck.client("suspender") as client:
        result = await client.get("/v1/admin/stores/stuck")

    assert result.status_code == 403


async def test_marks_a_stuck_store_failed_and_audits_it(stuck):
    async with stuck.client("reprovisioner") as client:
        result = await client.post("/v1/admin/stores/new/fail-stuck")

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["data"] == {
        "store_id": "new",
        "status": "FAILED",
        "changed": True,
    }
    assert stuck.repository.stores["new"].status is StoreStatus.FAILED
    row = stuck.auditor.rows[0]
    assert row["action"] == "admin.stores.fail_stuck"
    assert row["details"] == {"reason": "no progress while PROVISIONING"}


async def test_refuses_a_store_that_is_not_stuck_yet(fresh):
    async with fresh.client("reprovisioner") as client:
        result = await client.post("/v1/admin/stores/new/fail-stuck")

    assert result.status_code == 409
    assert fresh.repository.stores["new"].status is StoreStatus.PROVISIONING
    assert fresh.auditor.rows == []


async def test_refuses_a_store_that_is_not_provisioning(stuck):
    async with stuck.client("reprovisioner") as client:
        result = await client.post("/v1/admin/stores/live/fail-stuck")

    assert result.status_code == 409
    assert stuck.repository.stores["live"].status is StoreStatus.ACTIVE


async def test_unknown_store_is_404(stuck):
    async with stuck.client("reprovisioner") as client:
        result = await client.post("/v1/admin/stores/nope/fail-stuck")

    assert result.status_code == 404


@pytest.mark.parametrize("actor", ["reader", "suspender", "migrator", "other"])
async def test_fail_stuck_needs_stores_reprovision(stuck, actor):
    async with stuck.client(actor) as client:
        result = await client.post("/v1/admin/stores/new/fail-stuck")

    assert result.status_code == 403
    assert stuck.repository.stores["new"].status is StoreStatus.PROVISIONING


async def test_reports_when_more_stores_are_stuck_than_the_page_holds(
    stuck, monkeypatch
):
    monkeypatch.setattr("app.services.admin_stores.MAX_STUCK_LISTED", 1)
    stuck.repository.stores["new2"] = store("new2", status=StoreStatus.PROVISIONING)
    async with stuck.client("reader") as client:
        result = await client.get("/v1/admin/stores/stuck")

    body = result.json()["data"]
    assert len(body["stores"]) == 1
    assert body["truncated"] is True
