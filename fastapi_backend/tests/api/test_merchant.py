import time
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient

from app.api.auth import get_session_identity, require_internal_key
from app.api.deps import get_session
from app.api.merchant import OWNER_ADMIN, get_merchant_service, require_merchant
from app.core.firebase import VerifiedIdentity
from app.main import create_app
from app.models.platform.membership import MembershipRole
from app.models.platform.store import StoreStatus
from app.repositories.merchant import MerchantAccess, OrganizationRef, StoreRef
from app.services.merchant import MerchantService

KEY = "test-only-internal-service-key-not-for-deployment"
ALL = list(MembershipRole)
Access = Annotated[MerchantAccess, Depends(require_merchant())]
Managed = Annotated[MerchantAccess, Depends(require_merchant(OWNER_ADMIN))]
Write = Annotated[MerchantAccess, Depends(require_merchant(write=True))]

router = APIRouter(
    prefix="/test-merchant/{store_id}",
    tags=["test-merchant"],
    dependencies=[Depends(require_internal_key)],
)


@router.get("/read")
async def read(merchant: Access):
    return {
        "user_id": merchant.user_id,
        "organization": merchant.organization.id,
        "store": merchant.store.id,
        "role": merchant.role,
    }


@router.get("/manage")
async def manage(merchant: Managed):
    return {"ok": True}


@router.post("/write")
async def write(merchant: Write):
    return {"ok": True}


class FakeSession:
    def __init__(self):
        self.rollbacks = 0

    async def rollback(self):
        self.rollbacks += 1


class FakeMerchants:
    def __init__(self, found):
        self.found = found
        self.calls = []

    async def find_access(self, store_id, firebase_uid):
        self.calls.append((store_id, firebase_uid))
        return self.found


def access(role=MembershipRole.OWNER, status=StoreStatus.ACTIVE):
    return MerchantAccess(
        "user-1",
        OrganizationRef("org-1", "Acme", "acme"),
        StoreRef("store-1", "org-1", "Shop", "shop", status),
        role,
    )


def build(found, verified=True, authenticated=True):
    app = create_app()
    app.include_router(router)
    repo, session = FakeMerchants(found), FakeSession()
    app.dependency_overrides[get_merchant_service] = lambda: MerchantService(
        repo, session
    )
    app.dependency_overrides[get_session] = lambda: session
    if authenticated:
        app.dependency_overrides[get_session_identity] = lambda: VerifiedIdentity(
            "firebase-user", "ada@example.com", verified, int(time.time())
        )
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )
    return client, repo, session


@pytest.mark.parametrize("role", ALL)
async def test_every_role_may_read_an_active_store(role):
    client, repo, session = build(access(role))
    async with client:
        result = await client.get("/test-merchant/store-1/read")
    assert result.status_code == 200
    assert result.json() == {
        "user_id": "user-1",
        "organization": "org-1",
        "store": "store-1",
        "role": role.value,
    }
    assert repo.calls == [("store-1", "firebase-user")]
    assert session.rollbacks == 1


@pytest.mark.parametrize(
    ("role", "status_code"),
    [
        (MembershipRole.OWNER, 200),
        (MembershipRole.ADMIN, 200),
        (MembershipRole.STAFF, 403),
    ],
)
async def test_role_restriction_is_enforced(role, status_code):
    client, _, _ = build(access(role))
    async with client:
        result = await client.get("/test-merchant/store-1/manage")
    assert result.status_code == status_code
    if status_code == 403:
        assert result.json() == {"success": False, "error": "Forbidden"}


async def test_missing_membership_is_404():
    client, _, _ = build(None)
    async with client:
        result = await client.get("/test-merchant/store-1/read")
    assert result.status_code == 404
    assert result.json() == {"success": False, "error": "Store not found"}


async def test_missing_membership_is_404_even_for_role_restricted_routes():
    client, _, _ = build(None)
    async with client:
        result = await client.get("/test-merchant/store-1/manage")
    assert result.status_code == 404


async def test_not_found_response_does_not_vary_with_the_store_id():
    seen = []
    for store_id in ("missing", "other-orgs-store"):
        client, _, _ = build(None)
        async with client:
            result = await client.get(f"/test-merchant/{store_id}/read")
        seen.append((result.status_code, result.json()))
    assert seen[0] == seen[1]


@pytest.mark.parametrize("role", ALL)
@pytest.mark.parametrize("status", [StoreStatus.SUSPENDED, StoreStatus.PROVISIONING])
async def test_non_active_store_allows_reads_and_blocks_writes(role, status):
    client, _, _ = build(access(role, status))
    async with client:
        read_result = await client.get("/test-merchant/store-1/read")
        write_result = await client.post("/test-merchant/store-1/write")
    assert read_result.status_code == 200
    assert write_result.status_code == 403
    assert write_result.json() == {"success": False, "error": "Store is not active"}


@pytest.mark.parametrize("role", ALL)
async def test_active_store_allows_writes(role):
    client, _, _ = build(access(role))
    async with client:
        result = await client.post("/test-merchant/store-1/write")
    assert result.status_code == 200


async def test_archived_store_is_404_like_a_missing_one():
    client, _, _ = build(access(status=StoreStatus.ARCHIVED))
    async with client:
        read_result = await client.get("/test-merchant/store-1/read")
        write_result = await client.post("/test-merchant/store-1/write")
    assert read_result.status_code == 404
    assert write_result.status_code == 404
    assert read_result.json() == {"success": False, "error": "Store not found"}


async def test_role_check_comes_before_the_store_status_check():
    client, _, _ = build(access(MembershipRole.STAFF, StoreStatus.SUSPENDED))
    async with client:
        result = await client.get("/test-merchant/store-1/manage")
    assert result.json()["error"] == "Forbidden"


async def test_unverified_email_is_403_before_any_lookup():
    client, repo, _ = build(access(), verified=False)
    async with client:
        result = await client.get("/test-merchant/store-1/read")
    assert result.status_code == 403
    assert repo.calls == []


async def test_no_session_is_401_before_any_lookup():
    client, repo, _ = build(access(), authenticated=False)
    async with client:
        result = await client.get("/test-merchant/store-1/read")
    assert result.status_code == 401
    assert repo.calls == []


async def test_wrong_internal_key_is_401_before_any_lookup():
    client, repo, _ = build(access())
    async with client:
        result = await client.get(
            "/test-merchant/store-1/read", headers={"X-Internal-Key": "wrong"}
        )
    assert result.status_code == 401
    assert repo.calls == []


async def test_claims_in_the_request_are_ignored():
    client, _, _ = build(access(MembershipRole.STAFF))
    async with client:
        result = await client.get(
            "/test-merchant/store-1/manage",
            headers={"X-Role": "OWNER", "X-Organization-Id": "org-1"},
            params={"role": "OWNER"},
        )
    assert result.status_code == 403


def test_declaring_no_roles_fails_at_import_time():
    with pytest.raises(ValueError):
        require_merchant(frozenset())


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_mutating_method_is_a_write_even_without_the_write_flag(method):
    app_router = APIRouter(
        prefix="/forgot/{store_id}",
        tags=["forgot"],
        dependencies=[Depends(require_internal_key)],
    )

    @app_router.api_route("/x", methods=[method])
    async def forgot(merchant: Access):
        return {"ok": True}

    client, _, _ = build(access(status=StoreStatus.SUSPENDED))
    client._transport.app.include_router(app_router)  # type: ignore[attr-defined]
    async with client:
        result = await client.request(method, "/forgot/store-1/x")
    assert result.status_code == 403
    assert result.json()["error"] == "Store is not active"


@pytest.mark.parametrize("store_id", ["a" * 129, "bad%00id"])
async def test_malformed_store_id_is_the_same_404_without_a_lookup(store_id):
    client, repo, _ = build(access())
    async with client:
        result = await client.get(f"/test-merchant/{store_id}/read")
    assert result.status_code == 404
    assert result.json() == {"success": False, "error": "Store not found"}
    assert repo.calls == []
