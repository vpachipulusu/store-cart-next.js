# ruff: noqa: F401, F811 - the reused auth_context fixture is redefined as a test argument
"""KAN-257: ``POST /v1/auth/session`` must not mint a session for a 2FA user without a valid TOTP."""

import time
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import Response

from app.api.auth import get_auth_service
from app.api.deps import get_rate_limiter
from app.core.rate_limit import TOTP_SIGNIN_POLICY, RateLimitDecision
from app.core.totp import TotpCodec, generate_secret, token_at
from app.repositories.totp import TotpState
from app.services.auth import AuthService
from app.services.signin_totp import SignInTotpGuard
from tests.api.test_auth import (
    KEY,
    FakeIdentity,
    FakeRepository,
    FakeSession,
    auth_context,
    client_for,
)
from tests.fakes import FakeRateLimiter, RaisingRateLimiter, as_limiter

FERNET_KEY = Fernet.generate_key().decode()
SECRET = generate_secret()


class FakeTotpReader:
    def __init__(self, state: TotpState | None) -> None:
        self.state = state
        self.reads: list[str] = []

    async def get_state(self, uid: str) -> TotpState | None:
        self.reads.append(uid)
        return self.state


def enabled_state(ciphertext: str | None = None) -> TotpState:
    return TotpState(
        "platform-user", True, ciphertext or TotpCodec(FERNET_KEY).encrypt(SECRET)
    )


def wire(auth_context, state: TotpState | None, key: str | None = FERNET_KEY):
    app, identity, session, repository, limiter = auth_context
    reader = FakeTotpReader(state)

    def codec() -> TotpCodec:
        return TotpCodec(key)

    service = AuthService(identity, repository, session, SignInTotpGuard(reader, codec))
    app.dependency_overrides[get_auth_service] = lambda: service
    return app, identity, session, repository, limiter, reader


async def sign_in(app, **body: Any) -> Response:
    async with client_for(app) as client:
        return await client.post(
            "/v1/auth/session",
            json={"id_token": "id-token", **body},
            headers={"X-Internal-Key": KEY, "X-Client-IP": "192.0.2.1"},
        )


def assert_refused(
    response: Response, identity: FakeIdentity, repository: FakeRepository, code: str
) -> None:
    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "error": "Two-factor code required"
        if code == "totp_required"
        else "Invalid two-factor code",
        "code": code,
    }
    assert "session_cookie" not in response.text
    assert "mint" not in identity.calls
    assert repository.history == []
    assert repository.synced == []


def valid_code() -> str:
    return token_at(SECRET, time.time())


def wrong_code() -> str:
    valid = {token_at(SECRET, time.time() + d * 30) for d in (-1, 0, 1)}
    return next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in valid)


async def test_2fa_user_without_code_is_refused_totp_required(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    response = await sign_in(app)
    assert_refused(response, identity, repository, "totp_required")


@pytest.mark.parametrize(
    "code",
    ["12345", "1234567", "abcdef", "", " 123456", "123 456", "١٢٣٤٥٦"],
)
async def test_malformed_code_is_refused_totp_invalid(auth_context, code):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    response = await sign_in(app, totp_code=code)
    assert_refused(response, identity, repository, "totp_invalid")


async def test_well_formed_wrong_code_is_refused_totp_invalid(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    response = await sign_in(app, totp_code=wrong_code())
    assert_refused(response, identity, repository, "totp_invalid")


async def test_explicit_null_code_is_treated_as_missing(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    response = await sign_in(app, totp_code=None)
    assert_refused(response, identity, repository, "totp_required")


@pytest.mark.parametrize("code", [123456, "1" * 65, ["123456"]])
async def test_wrongly_typed_or_oversized_code_is_422_and_mints_nothing(
    auth_context, code
):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    response = await sign_in(app, totp_code=code)
    assert response.status_code == 422
    assert "code" not in response.json()
    assert "mint" not in identity.calls
    assert repository.history == []


async def test_refresh_ignores_totp_for_a_2fa_user(auth_context):
    app, _, _, repository, _, reader = wire(auth_context, enabled_state())
    async with client_for(app) as client:
        response = await client.post(
            "/v1/auth/session/refresh",
            json={"id_token": "id-token", "totp_code": wrong_code()},
            headers={"X-Internal-Key": KEY, "X-Session-Token": "session"},
        )
    assert response.status_code == 200
    assert reader.reads == []  # refresh never consults the second factor
    assert repository.history == []


async def test_real_wiring_attaches_the_guard_and_builds_the_codec_lazily(
    monkeypatch,
):
    from pydantic import SecretStr

    from app.api.auth import get_auth_service, totp_codec
    from app.core.config import settings
    from app.core.totp import TotpUnavailable

    service = get_auth_service(None, FakeSession())  # type: ignore[arg-type]
    assert isinstance(service.totp_guard, SignInTotpGuard)
    monkeypatch.setattr(settings, "TOTP_ENCRYPTION_KEY", None)
    with pytest.raises(TotpUnavailable):
        totp_codec()
    monkeypatch.setattr(settings, "TOTP_ENCRYPTION_KEY", SecretStr(FERNET_KEY))
    assert totp_codec().decrypt(TotpCodec(FERNET_KEY).encrypt("x")) == "x"


async def test_correct_code_issues_cookie_and_records_login(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    response = await sign_in(app, totp_code=valid_code())
    assert response.status_code == 200
    assert response.json()["data"]["session_cookie"] == "minted-session-cookie"
    assert identity.calls == ["verify-id", "mint"]
    assert [h[:2] for h in repository.history] == [("platform-user", "192.0.2.1")]


async def test_user_without_2fa_is_unchanged(auth_context):
    state = TotpState("platform-user", False, None)
    app, identity, _, repository, _, reader = wire(auth_context, state)
    response = await sign_in(app)
    assert response.status_code == 200
    assert identity.calls == ["verify-id", "mint"]
    assert len(repository.history) == 1
    assert reader.reads == ["firebase-user"]


async def test_signup_without_user_row_is_unchanged(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, None)
    response = await sign_in(app)
    assert response.status_code == 200
    assert identity.calls == ["verify-id", "mint"]
    assert len(repository.history) == 1


async def test_pending_enrolment_is_not_enforced(auth_context):
    state = TotpState("platform-user", False, TotpCodec(FERNET_KEY).encrypt(SECRET))
    app, *_ = wire(auth_context, state)
    assert (await sign_in(app)).status_code == 200


@pytest.mark.parametrize(
    "state",
    [
        TotpState("platform-user", True, "not-a-fernet-token"),
        TotpState("platform-user", True, None),
        TotpState(
            "platform-user",
            True,
            TotpCodec(Fernet.generate_key().decode()).encrypt(SECRET),
        ),
    ],
    ids=["garbage", "missing", "other-key"],
)
async def test_undecryptable_secret_fails_closed(auth_context, state):
    app, identity, _, repository, *_ = wire(auth_context, state)
    response = await sign_in(app, totp_code=valid_code())
    assert response.status_code == 503
    assert "session_cookie" not in response.text
    assert "mint" not in identity.calls
    assert repository.history == []


async def test_missing_encryption_key_fails_closed_for_2fa_user(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state(), key=None)
    response = await sign_in(app, totp_code=valid_code())
    assert response.status_code == 503
    assert "mint" not in identity.calls
    assert repository.history == []


async def test_missing_key_does_not_affect_non_2fa_user(auth_context):
    state = TotpState("platform-user", False, None)
    app, *_ = wire(auth_context, state, key=None)
    assert (await sign_in(app)).status_code == 200


class OnlyTotpPolicyLimits:
    """Lets the sign-in AUTH_POLICY always pass, so any 429 must come from TOTP_SIGNIN_POLICY."""

    enabled = True

    def __init__(self) -> None:
        self.inner = FakeRateLimiter()

    async def hit(self, identifier: str, policy: Any):
        if policy is TOTP_SIGNIN_POLICY:
            return await self.inner.hit(identifier, policy)
        return RateLimitDecision(True, policy.limit, policy.limit, 4_000_000_000.0)


def only_totp_limits(app) -> OnlyTotpPolicyLimits:
    limiter = OnlyTotpPolicyLimits()
    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(limiter)  # type: ignore[arg-type]
    return limiter


async def test_code_attempts_are_limited_per_uid_by_the_totp_policy(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    limiter = only_totp_limits(app)
    wrong = wrong_code()
    statuses = [
        (await sign_in(app, totp_code=wrong)).status_code
        for _ in range(TOTP_SIGNIN_POLICY.limit + 1)
    ]
    assert statuses == [401] * TOTP_SIGNIN_POLICY.limit + [429]
    assert [i for i, _ in limiter.inner.hits] == ["totp_signin:user:firebase-user"] * (
        TOTP_SIGNIN_POLICY.limit + 1
    )
    # Even the correct code is refused, with a Retry-After, once the budget is spent.
    refused = await sign_in(app, totp_code=valid_code())
    assert refused.status_code == 429 and "retry-after" in refused.headers
    assert "mint" not in identity.calls
    assert repository.history == []


async def test_totp_budget_is_per_uid(auth_context):
    app, identity, *_ = wire(auth_context, enabled_state())
    only_totp_limits(app)
    for _ in range(TOTP_SIGNIN_POLICY.limit + 1):
        await sign_in(app, totp_code=wrong_code())
    identity.claims["uid"] = "someone-else"
    response = await sign_in(app, totp_code=wrong_code())
    assert response.status_code == 401  # refused as a wrong code, not rate limited


async def test_requests_without_a_code_do_not_spend_the_totp_budget(auth_context):
    app, *_ = wire(auth_context, enabled_state())
    limiter = only_totp_limits(app)
    for _ in range(TOTP_SIGNIN_POLICY.limit * 2):
        assert (await sign_in(app)).status_code == 401
    assert limiter.inner.hits == []
    assert (await sign_in(app, totp_code=valid_code())).status_code == 200


async def test_totp_limiter_outage_fails_closed(auth_context):
    app, identity, _, repository, *_ = wire(auth_context, enabled_state())
    working, outage = FakeRateLimiter(), RaisingRateLimiter()

    class OutageOnTotpPolicy:
        enabled = True

        async def hit(self, identifier: str, policy: Any):
            target = outage if policy is TOTP_SIGNIN_POLICY else working
            return await target.hit(identifier, policy)

    app.dependency_overrides[get_rate_limiter] = lambda: as_limiter(
        OutageOnTotpPolicy()  # type: ignore[arg-type]
    )
    response = await sign_in(app, totp_code=valid_code())
    assert response.status_code == 503
    assert "mint" not in identity.calls
    assert repository.history == []


async def test_code_and_secret_never_appear_in_logs_or_responses(auth_context, caplog):
    app, *_ = wire(auth_context, enabled_state())
    code = wrong_code()
    with caplog.at_level("DEBUG"):
        response = await sign_in(app, totp_code=code)
    assert code not in response.text
    assert code not in caplog.text
    assert SECRET not in caplog.text


async def test_unusable_secret_logs_without_code_or_secret(auth_context, caplog):
    ciphertext = TotpCodec(Fernet.generate_key().decode()).encrypt(SECRET)
    app, *_ = wire(auth_context, enabled_state(ciphertext))
    code = valid_code()
    with caplog.at_level("DEBUG"):
        response = await sign_in(app, totp_code=code)
    assert response.status_code == 503
    assert any("two-factor secret unusable" in r.getMessage() for r in caplog.records)
    assert code not in caplog.text and SECRET not in caplog.text
    assert code not in response.text and ciphertext not in caplog.text


async def test_openapi_documents_codes_and_leaves_refresh_unchanged(auth_context):
    app, *_ = auth_context
    schema = app.openapi()
    schemas = schema["components"]["schemas"]
    assert "totp_code" in schemas["SignInRequest"]["properties"]
    assert "totp_code" not in schemas["SessionRequest"]["properties"]
    session_401 = schema["paths"]["/v1/auth/session"]["post"]["responses"]["401"]
    ref = session_401["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/AuthChallengeErrorResponse")
    code = schemas["AuthChallengeErrorResponse"]["properties"]["code"]
    assert {
        entry for variant in code["anyOf"] for entry in variant.get("enum", [])
    } == {
        "totp_required",
        "totp_invalid",
    }
    refresh = schema["paths"]["/v1/auth/session/refresh"]["post"]
    body = refresh["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert body.endswith("/SessionRequest")
