"""Build ``Upstash-Signature`` JWTs the way QStash does (KAN-56 tests)."""

import base64
import hashlib
import hmac
import json
import time


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(
    body: bytes,
    url: str,
    key: str,
    *,
    now: float | None = None,
    claims: dict[str, object] | None = None,
    alg: str = "HS256",
) -> str:
    issued = int(time.time() if now is None else now)
    payload: dict[str, object] = {
        "iss": "Upstash",
        "sub": url,
        "exp": issued + 300,
        "nbf": issued - 10,
        "iat": issued - 10,
        "jti": "jwt_1",
        "body": b64(hashlib.sha256(body).digest()),
    }
    payload.update(claims or {})
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    signing_input = f"{head}.{b64(json.dumps(payload).encode())}"
    mac = hmac.new(key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(mac)}"
