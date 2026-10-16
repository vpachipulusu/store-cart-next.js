import base64
import hashlib
import hmac
import json

import pytest

from app.core.qstash_signature import InvalidQStashSignature, verify_qstash_signature

URL = "https://api.example.test/internal/provisioning/step"
KEY = "current-signing-key-for-tests"
NEXT_KEY = "next-signing-key-for-tests"
NOW = 1_800_000_000
BODY = b'{"store_id":"abc12345","step":"create_database"}'


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(
    body: bytes = BODY,
    *,
    key: str = KEY,
    url: str = URL,
    claims: dict[str, object] | None = None,
    alg: str = "HS256",
) -> str:
    payload: dict[str, object] = {
        "iss": "Upstash",
        "sub": url,
        "exp": NOW + 300,
        "nbf": NOW - 10,
        "iat": NOW - 10,
        "jti": "jwt_1",
        "body": b64(hashlib.sha256(body).digest()),
    }
    payload.update(claims or {})
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    signing_input = f"{head}.{b64(json.dumps(payload).encode())}"
    mac = hmac.new(key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(mac)}"


def verify(token: str | None, body: bytes = BODY, keys=(KEY, NEXT_KEY)) -> None:
    verify_qstash_signature(body, token, URL, keys, now=NOW)


def test_accepts_a_valid_signature():
    verify(make_token())


def test_accepts_a_signature_made_with_the_next_key():
    verify(make_token(key=NEXT_KEY))


@pytest.mark.parametrize("token", [None, "", "a.b", "not-a-jwt", "a.b.c.d"])
def test_rejects_missing_or_malformed_tokens(token):
    with pytest.raises(InvalidQStashSignature):
        verify(token)


def test_rejects_a_signature_from_another_key():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(key="someone-elses-key"))


def test_rejects_when_no_signing_key_is_configured():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(), keys=())


def test_rejects_a_tampered_body():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(), body=BODY + b" ")


def test_rejects_a_token_issued_for_another_url():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(url="https://api.example.test/other"))


def test_rejects_an_expired_token():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(claims={"exp": NOW - 60}))


def test_rejects_a_token_that_is_not_valid_yet():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(claims={"nbf": NOW + 600}))


def test_rejects_a_wrong_issuer():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(claims={"iss": "Evil"}))


def test_rejects_the_none_algorithm():
    with pytest.raises(InvalidQStashSignature):
        verify(make_token(alg="none"))
