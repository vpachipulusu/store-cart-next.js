"""POST /v1/admin/stores/{id}/reprovision through the real dependency chain (KAN-200)."""

import pytest

from app.api.v1.admin_stores import get_admin_stores_service
from app.models.platform.store import StoreStatus
from app.services.admin_stores import (
    MAX_REPROVISION_ATTEMPTS,
    AdminStoresService,
)
from tests.api.test_admin_stores import Harness
from tests.fakes_admin_stores import store


class ReprovisionHarness(Harness):
    def __init__(self) -> None:
        super().__init__()
        self.grants["reprovisioner"] = ("admin", ["stores.reprovision"])
        self.repository.stores["broken"] = store("broken", status=StoreStatus.FAILED)
        self.started: list[str] = []
        self.start_ok = True

        async def start(store_id: str, attempt: int) -> bool:
            self.started.append(store_id)
            return self.start_ok

        async def migrate(store_id: str) -> int:
            return 0

        self.app.dependency_overrides[get_admin_stores_service] = lambda: (
            AdminStoresService(
                self.repository,
                self.session,
                self.auditor,
                migrate,
                start_provisioning=start,
            )
        )


@pytest.fixture
def harness() -> ReprovisionHarness:
    return ReprovisionHarness()


@pytest.mark.parametrize(
    "actor", ["reader", "suspender", "migrator", "other", "nobody"]
)
async def test_other_permissions_are_403_and_change_nothing(harness, actor):
    async with harness.client(actor) as client:
        result = await client.post("/v1/admin/stores/broken/reprovision")

    assert result.status_code == 403
    assert result.json() == {"success": False, "error": "Forbidden"}
    assert harness.started == [] and harness.auditor.rows == []
    assert harness.repository.stores["broken"].status is StoreStatus.FAILED


async def test_unauthenticated_is_401(harness):
    async with harness.client(None) as client:
        result = await client.post("/v1/admin/stores/broken/reprovision")

    assert result.status_code == 401


@pytest.mark.parametrize("actor", ["reprovisioner", "boss"])
async def test_permitted_admin_restarts_provisioning(harness, actor):
    async with harness.client(actor) as client:
        result = await client.post("/v1/admin/stores/broken/reprovision")

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json() == {
        "success": True,
        "data": {
            "store_id": "broken",
            "status": "PROVISIONING",
            "attempt": 1,
            "max_attempts": MAX_REPROVISION_ATTEMPTS,
        },
    }
    assert harness.started == ["broken"]
    assert harness.auditor.rows[0]["action"] == "admin.stores.reprovision"


async def test_store_that_is_not_failed_is_409(harness):
    async with harness.client() as client:
        result = await client.post("/v1/admin/stores/live/reprovision")

    assert result.status_code == 409
    assert result.json()["error"] == "Operation not allowed in the current state"
    assert harness.started == []


async def test_unknown_store_is_404(harness):
    async with harness.client() as client:
        result = await client.post("/v1/admin/stores/nope/reprovision")

    assert result.status_code == 404
    assert result.json() == {"success": False, "error": "Store not found"}
    assert "cache-control" not in result.headers
    assert harness.started == []


async def test_store_id_with_unsafe_characters_is_422(harness):
    async with harness.client() as client:
        result = await client.post("/v1/admin/stores/a$b/reprovision")

    assert result.status_code == 422


async def test_cap_reached_is_409_with_its_own_message(harness):
    harness.repository.reprovisions["broken"] = MAX_REPROVISION_ATTEMPTS
    async with harness.client() as client:
        result = await client.post("/v1/admin/stores/broken/reprovision")

    assert result.status_code == 409
    assert result.json()["error"] == "Provisioning retry limit reached"
    assert harness.started == []


async def test_enqueue_failure_is_a_generic_502(harness):
    harness.start_ok = False
    async with harness.client() as client:
        result = await client.post("/v1/admin/stores/broken/reprovision")

    assert result.status_code == 502
    assert result.json() == {
        "success": False,
        "error": "Provisioning could not be started",
    }


async def test_audit_failure_is_503_with_retry_after(harness):
    async def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    harness.auditor.record = broken
    async with harness.client("reprovisioner") as client:
        result = await client.post("/v1/admin/stores/broken/reprovision")

    assert result.status_code == 503
    assert result.headers["retry-after"] == "5"
    assert harness.started == []
