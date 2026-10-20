# ruff: noqa: F811 - fixtures imported from test_auth_refresh_e2e are redefined as test arguments
"""End to end: ``POST /v1/auth/session`` with TOTP on real Postgres (KAN-257).

Same contract as ``test_auth_refresh_e2e.py`` (it reuses its fixtures): runs only when
``TEST_DATABASE_URL`` points at a throwaway local ``*_test`` database. Only the Firebase
adapter is replaced; the auth service, TOTP repository, codec and transaction handling are
the production code.
"""

import time

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.core.totp import TotpCodec, generate_secret, token_at
from tests.api.test_auth_refresh_e2e import (  # noqa: F401 - fixtures
    TEST_DATABASE_URL,
    TokenTableIdentity,
    claims,
    client,
    database_url,
    engine,
    identity,
    scalar,
    seed_user,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

SECRET = generate_secret()
HISTORY = "SELECT count(*) FROM login_history"


@pytest.fixture
def codec(monkeypatch: pytest.MonkeyPatch) -> TotpCodec:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOTP_ENCRYPTION_KEY", SecretStr(key))
    return TotpCodec(key)


async def enable_2fa(engine: AsyncEngine, uid: str, ciphertext: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE users SET two_factor_enabled = true, "
                "two_factor_secret = :c WHERE firebase_uid = :uid"
            ),
            {"c": ciphertext, "uid": uid},
        )


def sign_in(client: AsyncClient, **extra: str):
    return client.post("/v1/auth/session", json={"id_token": "id-ada", **extra})


@pytest.fixture
def ada_token(identity: TokenTableIdentity) -> None:
    identity.id_tokens["id-ada"] = claims("ada", verified=True)


async def test_2fa_user_without_code_gets_no_cookie_and_no_history(
    client: AsyncClient, engine: AsyncEngine, codec: TotpCodec, ada_token: None
) -> None:
    await seed_user(engine, "ada", verified=True)
    await enable_2fa(engine, "ada", codec.encrypt(SECRET))

    response = await sign_in(client)

    assert response.status_code == 401
    assert response.json()["code"] == "totp_required"
    assert "new-cookie" not in response.text
    assert await scalar(engine, HISTORY) == 0


async def test_wrong_code_gets_no_cookie_and_no_history(
    client: AsyncClient, engine: AsyncEngine, codec: TotpCodec, ada_token: None
) -> None:
    await seed_user(engine, "ada", verified=True)
    await enable_2fa(engine, "ada", codec.encrypt(SECRET))
    valid = {token_at(SECRET, time.time() + d * 30) for d in (-1, 0, 1)}
    wrong = next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in valid)

    response = await sign_in(client, totp_code=wrong)

    assert response.status_code == 401
    assert response.json()["code"] == "totp_invalid"
    assert "new-cookie" not in response.text
    assert await scalar(engine, HISTORY) == 0


async def test_correct_code_issues_cookie_and_records_login(
    client: AsyncClient, engine: AsyncEngine, codec: TotpCodec, ada_token: None
) -> None:
    await seed_user(engine, "ada", verified=True)
    await enable_2fa(engine, "ada", codec.encrypt(SECRET))

    response = await sign_in(client, totp_code=token_at(SECRET, time.time()))

    assert response.status_code == 200
    assert response.json()["data"]["session_cookie"] == "new-cookie-for-id-ada"
    assert await scalar(engine, HISTORY) == 1


async def test_undecryptable_secret_fails_closed(
    client: AsyncClient, engine: AsyncEngine, codec: TotpCodec, ada_token: None
) -> None:
    await seed_user(engine, "ada", verified=True)
    await enable_2fa(engine, "ada", "not-a-fernet-token")

    response = await sign_in(client, totp_code=token_at(SECRET, time.time()))

    assert response.status_code == 503
    assert "new-cookie" not in response.text
    assert await scalar(engine, HISTORY) == 0


async def test_user_without_2fa_and_signup_are_unchanged(
    client: AsyncClient, engine: AsyncEngine, codec: TotpCodec, ada_token: None
) -> None:
    # Signup: no user row yet.
    first = await sign_in(client)
    assert first.status_code == 200
    assert await scalar(engine, "SELECT count(*) FROM users") == 1
    # Existing user without 2FA signs in again.
    second = await sign_in(client)
    assert second.status_code == 200
    assert await scalar(engine, HISTORY) == 2
