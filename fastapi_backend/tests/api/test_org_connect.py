"""Connect routes with fakes behind the real router, dependencies and error mapping (KAN-67)."""

import logging
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.auth import get_current_identity
from app.api.me import get_current_user_id
from app.api.v1.org_connect import get_connect_service, get_stripe_connect_client
from app.core.config import settings
from app.core.firebase import VerifiedIdentity
from app.main import create_app
from app.models.platform.membership import MembershipRole
from app.services.org_billing import allowed_origins
from app.services.stripe_connect import ConnectService
from tests.fakes_billing import FakeCommitSession
from tests.fakes_connect import FakeConnectStore, FakeStripeConnect, connect_record

KEY = "test-only-internal-service-key-not-for-deployment"
OK_URL = "https://app.example.com/settings"
BASE = "/v1/organizations/org1/connect"
BODY = {"return_url": OK_URL, "refresh_url": OK_URL}


class Harness:
    def __init__(self) -> None:
        self.store = FakeConnectStore()
        self.stripe = FakeStripeConnect()
        self.session = FakeCommitSession()
        self.store.add(connect_record(), "owner", MembershipRole.OWNER)
        self.store.roles[("org1", "staff")] = MembershipRole.STAFF
        self.store.add(connect_record(id="org2"), "other-owner", MembershipRole.OWNER)
        self.app = create_app()

        async def current_user(
            x_test_user: Annotated[str | None, Header()] = None,
        ) -> str:
            if x_test_user is None:
                raise HTTPException(401, "Invalid authentication")
            return x_test_user

        def service() -> ConnectService:
            return ConnectService(
                self.store,
                self.store,
                self.session,  # type: ignore[arg-type]
                self.stripe,
                allowed_origins("https://app.example.com"),
            )

        self.app.dependency_overrides[get_current_user_id] = current_user
        self.app.dependency_overrides[get_current_identity] = lambda: VerifiedIdentity(
            "fb-test", "test@example.com", True, 0
        )
        self.app.dependency_overrides[get_connect_service] = service


@pytest.fixture
def harness() -> Harness:
    return Harness()


def client(harness: Harness, user: str | None = "owner") -> AsyncClient:
    headers = {"X-Internal-Key": KEY}
    if user:
        headers["X-Test-User"] = user
    return AsyncClient(
        transport=ASGITransport(app=harness.app, raise_app_exceptions=False),
        base_url="http://test",
        headers=headers,
    )


async def test_missing_internal_key_is_401(harness):
    async with client(harness) as http:
        http.headers.pop("X-Internal-Key")
        result = await http.get(BASE)

    assert result.status_code == 401


async def test_status_reports_no_account_for_a_new_organisation(harness):
    async with client(harness) as http:
        result = await http.get(BASE)

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json() == {
        "success": True,
        "data": {
            "has_account": False,
            "charges_enabled": False,
            "payouts_enabled": False,
            "details_submitted": False,
        },
    }


async def test_status_never_exposes_the_account_id(harness):
    harness.store.orgs["org1"] = connect_record(
        stripe_connect_account_id="acct_secretish", connect_charges_enabled=True
    )

    async with client(harness) as http:
        result = await http.get(BASE)

    assert result.json()["data"]["charges_enabled"] is True
    assert "acct_" not in result.text


async def test_staff_is_403_and_strangers_and_other_orgs_are_404(harness):
    async with client(harness, "staff") as http:
        staff = await http.get(BASE)
    async with client(harness, "nobody") as http:
        stranger = await http.get(BASE)
    async with client(harness, "other-owner") as http:
        other = [
            await http.get(BASE),
            await http.post(f"{BASE}/onboarding-link", json=BODY),
        ]

    assert (staff.status_code, staff.json()) == (
        403,
        {"success": False, "error": "Forbidden"},
    )
    assert stranger.status_code == 404
    assert [r.status_code for r in other] == [404, 404]
    assert harness.stripe.calls == []


async def test_onboarding_link_returns_the_hosted_url_with_a_server_side_key(harness):
    harness.store.orgs["org1"] = connect_record(stripe_connect_account_id="acct_1")

    async with client(harness) as http:
        result = await http.post(
            f"{BASE}/onboarding-link",
            json=BODY,
            headers={"Idempotency-Key": "client-key-1"},
        )

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["data"] == {"url": "https://connect.stripe.test/setup/abc"}
    key = harness.stripe.last("create_account_link")["idempotency_key"]
    assert key.startswith("sc-connect-link-org1-") and "client-key-1" not in key


@pytest.mark.parametrize(
    "url", ["https://evil.example.com/", "javascript:alert(1)", "//evil.test/x"]
)
async def test_foreign_urls_are_422_and_never_reach_stripe(harness, url):
    async with client(harness) as http:
        result = await http.post(
            f"{BASE}/onboarding-link", json={**BODY, "refresh_url": url}
        )

    assert (result.status_code, result.json()["error"]) == (422, "Invalid return URL")
    assert harness.stripe.calls == []


async def test_unknown_body_fields_are_rejected(harness):
    async with client(harness) as http:
        result = await http.post(
            f"{BASE}/onboarding-link", json={**BODY, "account": "acct_evil"}
        )

    assert result.status_code == 422
    assert harness.stripe.calls == []


async def test_stripe_outage_is_a_generic_502_without_stripe_text(harness, caplog):
    harness.stripe.fail_on = "all"

    with caplog.at_level(logging.INFO):
        async with client(harness) as http:
            result = await http.post(f"{BASE}/onboarding-link", json=BODY)

    assert (result.status_code, result.json()) == (
        502,
        {"success": False, "error": "Payment provider unavailable"},
    )
    assert "BillingUnavailable" in caplog.text


def test_unconfigured_secret_key_is_503_and_a_configured_one_builds_a_client(
    monkeypatch,
):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    with pytest.raises(HTTPException) as raised:
        get_stripe_connect_client()

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", SecretStr("sk_test_x"))

    assert raised.value.status_code == 503
    assert get_stripe_connect_client() is not None
