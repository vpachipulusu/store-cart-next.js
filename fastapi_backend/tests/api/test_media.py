"""POST /v1/stores/{id}/uploads/images behind the real router, auth and merchant checks."""

import logging
from typing import Annotated

import pytest
from fastapi import Header
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.auth import get_current_identity
from app.api.deps import get_media_upload_service
from app.api.merchant import get_merchant_service
from app.core.config import settings
from app.core.firebase import VerifiedIdentity
from app.main import create_app
from app.models.platform.membership import MembershipRole
from app.models.platform.store import StoreStatus
from app.repositories.merchant import MerchantAccess, OrganizationRef, StoreRef
from app.services.media_uploads import MAX_IMAGE_BYTES, MediaUploadService
from app.services.merchant import MerchantService
from tests.services.test_media_uploads import FakeSigner

KEY = "test-only-internal-service-key-not-for-deployment"
URL = "/v1/stores/store-1/uploads/images"
BODY = {"content_type": "image/png", "size_bytes": 2048}


class FakeSession:
    async def rollback(self) -> None:
        pass


class FakeMerchants:
    def __init__(self, accesses: dict[tuple[str, str], MerchantAccess]) -> None:
        self.accesses = accesses

    async def find_access(self, store_id: str, firebase_uid: str):
        return self.accesses.get((store_id, firebase_uid))


def access(role: MembershipRole, status: StoreStatus = StoreStatus.ACTIVE):
    return MerchantAccess(
        "user-1",
        OrganizationRef("org-1", "Acme", "acme"),
        StoreRef("store-1", "org-1", "Shop", "shop", status),
        role,
    )


class Harness:
    def __init__(self, role=MembershipRole.OWNER, status=StoreStatus.ACTIVE) -> None:
        self.app = create_app()
        self.signer = FakeSigner()
        service = MediaUploadService(self.signer, "https://media.example.com")
        merchants = FakeMerchants({("store-1", "owner"): access(role, status)})

        async def identity(
            x_test_user: Annotated[str, Header()] = "owner",
        ) -> VerifiedIdentity:
            return VerifiedIdentity(x_test_user, "a@example.com", True, 0)

        self.app.dependency_overrides[get_current_identity] = identity
        self.app.dependency_overrides[get_merchant_service] = lambda: MerchantService(
            merchants,  # type: ignore[arg-type]
            FakeSession(),  # type: ignore[arg-type]
        )
        self.app.dependency_overrides[get_media_upload_service] = lambda: service

    def client(self, user: str = "owner") -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"X-Internal-Key": KEY, "X-Test-User": user},
        )


@pytest.fixture
def harness():
    built = Harness()
    yield built
    built.app.dependency_overrides.clear()


async def test_missing_internal_key_is_401(harness):
    async with harness.client() as http:
        http.headers.pop("X-Internal-Key")
        result = await http.post(URL, json=BODY)

    assert result.status_code == 401


async def test_foreign_store_is_404(harness):
    async with harness.client(user="stranger") as http:
        result = await http.post(URL, json=BODY)

    assert result.status_code == 404
    assert harness.signer.calls == []


async def test_staff_is_403():
    built = Harness(role=MembershipRole.STAFF)
    async with built.client() as http:
        result = await http.post(URL, json=BODY)

    assert result.status_code == 403
    assert built.signer.calls == []


async def test_non_active_store_is_rejected():
    built = Harness(status=StoreStatus.SUSPENDED)
    async with built.client() as http:
        result = await http.post(URL, json=BODY)

    assert result.status_code == 403
    assert built.signer.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"content_type": "image/svg+xml", "size_bytes": 10},
        {"content_type": "image/png", "size_bytes": 0},
        {"content_type": "image/png", "size_bytes": MAX_IMAGE_BYTES + 1},
        {"content_type": "image/png"},
        {"content_type": "image/png", "size_bytes": 10, "key": "../x"},
    ],
)
async def test_invalid_body_is_422(harness, body):
    async with harness.client() as http:
        result = await http.post(URL, json=body)

    assert result.status_code == 422
    assert harness.signer.calls == []


async def test_unconfigured_r2_is_503(harness, monkeypatch):
    del harness.app.dependency_overrides[get_media_upload_service]
    monkeypatch.setattr(deps, "_media_upload_service", None)
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", None)

    async with harness.client() as http:
        result = await http.post(URL, json=BODY)

    assert result.status_code == 503
    assert result.json() == {
        "success": False,
        "error": "Service temporarily unavailable",
    }


@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
async def test_owner_and_admin_receive_a_presigned_put(role):
    built = Harness(role=role)
    async with built.client() as http:
        result = await http.post(URL, json=BODY)

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    data = result.json()["data"]
    assert data["method"] == "PUT"
    assert data["headers"] == {"Content-Type": "image/png"}
    assert data["key"].startswith("stores/store-1/")
    assert data["key"].endswith(".png")
    assert data["public_url"] == f"https://media.example.com/{data['key']}"
    assert data["upload_url"].startswith("https://signed.example.com/")
    assert data["expires_at"]


async def test_presigned_url_is_not_logged(harness, caplog):
    caplog.set_level(logging.DEBUG)

    async with harness.client() as http:
        result = await http.post(URL, json=BODY)

    assert result.status_code == 200
    assert "X-Amz-Signature" not in caplog.text
    assert "signed.example.com" not in caplog.text
