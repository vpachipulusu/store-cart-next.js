"""``require_merchant(any_status=True)`` (KAN-242): role checked, store status left to the route."""

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
AnyStatus = Annotated[
    MerchantAccess, Depends(require_merchant(OWNER_ADMIN, any_status=True))
]
Writes = Annotated[MerchantAccess, Depends(require_merchant(OWNER_ADMIN))]

router = APIRouter(
    prefix="/test-any-status/{store_id}",
    tags=["test-any-status"],
    dependencies=[Depends(require_internal_key)],
)


@router.post("/any")
async def any_status(merchant: AnyStatus):
    return {"status": merchant.store.status}


@router.post("/write")
async def write(merchant: Writes):
    return {"ok": True}


class FakeSession:
    async def rollback(self):
        return None


class FakeMerchants:
    def __init__(self, found):
        self.found = found

    async def find_access(self, store_id, firebase_uid):
        return self.found


def access(role: MembershipRole, status: StoreStatus) -> MerchantAccess:
    return MerchantAccess(
        "user-1",
        OrganizationRef("org-1", "Acme", "acme"),
        StoreRef("store-1", "org-1", "Shop", "shop", status),
        role,
    )


def client_for(found: MerchantAccess | None) -> AsyncClient:
    app = create_app()
    app.include_router(router)
    session = FakeSession()
    app.dependency_overrides[get_merchant_service] = lambda: MerchantService(
        FakeMerchants(found), session
    )
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_session_identity] = lambda: VerifiedIdentity(
        "firebase-user", "ada@example.com", True, int(time.time())
    )
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Internal-Key": KEY},
    )


@pytest.mark.parametrize("status", [StoreStatus.FAILED, StoreStatus.PROVISIONING])
async def test_a_post_reaches_a_store_that_is_not_active(status):
    async with client_for(access(MembershipRole.OWNER, status)) as client:
        result = await client.post("/test-any-status/store-1/any")
        default = await client.post("/test-any-status/store-1/write")

    assert result.status_code == 200
    assert default.status_code == 403  # the default still refuses writes


async def test_the_role_is_still_enforced():
    async with client_for(access(MembershipRole.STAFF, StoreStatus.FAILED)) as client:
        result = await client.post("/test-any-status/store-1/any")

    assert result.status_code == 403


@pytest.mark.parametrize(
    "found", [access(MembershipRole.OWNER, StoreStatus.ARCHIVED), None]
)
async def test_an_archived_or_unknown_store_is_still_not_found(found):
    async with client_for(found) as client:
        result = await client.post("/test-any-status/store-1/any")

    assert result.status_code == 404
