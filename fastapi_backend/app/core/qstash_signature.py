"""QStash request signature verification (KAN-56).

QStash signs every delivery with an ``Upstash-Signature`` header: an HS256 JWT keyed with
the current or next signing key. Claims checked here: ``iss`` is ``Upstash``, ``sub`` is
the URL QStash called, ``exp``/``nbf`` bound its lifetime and ``body`` is the URL-safe
base64 SHA-256 of the exact raw body. Nothing here logs or echoes the token, body or keys.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from collections.abc import Sequence
from typing import Any

ISSUER = "Upstash"
CLOCK_SKEW_SECONDS = 5


class InvalidQStashSignature(Exception):
    """The signature header is missing, malformed, expired or does not match.

    ``reason`` names the failed check (KAN-255) and ``claimed_url`` is the ``sub`` of a
    token whose HMAC verified but was issued for another URL. Neither is secret.
    """

    def __init__(self, reason: str = "malformed", claimed_url: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.claimed_url = claimed_url


_B64URL = re.compile(r"[A-Za-z0-9_-]*")
# QStash tokens live minutes; a far-future exp would only come from a forged one.
MAX_LIFETIME_SECONDS = 3600


def _b64decode(value: str) -> bytes:
    if not _B64URL.fullmatch(value):
        raise InvalidQStashSignature
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        raise InvalidQStashSignature from None


def _signed_by_any(signing_input: bytes, signature: bytes, keys: Sequence[str]) -> bool:
    matched = False
    for key in keys:
        expected = hmac.new(key.encode(), signing_input, hashlib.sha256).digest()
        # No short-circuit: every configured key is compared.
        matched |= hmac.compare_digest(expected, signature)
    return matched


def _claims(token: str, keys: Sequence[str]) -> dict[str, Any]:
    """Claims of ``token`` once its HMAC is verified; nothing is parsed before that."""
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidQStashSignature("malformed")
    head, payload, signature = parts
    signing_input = f"{head}.{payload}".encode()
    if not _signed_by_any(signing_input, _b64decode(signature), keys):
        raise InvalidQStashSignature("signature")
    try:
        header = json.loads(_b64decode(head))
        claims = json.loads(_b64decode(payload))
    except ValueError:
        raise InvalidQStashSignature from None
    if (
        not isinstance(header, dict)
        or header.get("alg") != "HS256"
        or not isinstance(claims, dict)
    ):
        raise InvalidQStashSignature
    return claims


def verify_qstash_signature(
    body: bytes,
    token: str | None,
    url: str,
    signing_keys: Sequence[str],
    *,
    now: float | None = None,
) -> None:
    """Raise InvalidQStashSignature unless ``token`` signs this ``body`` for ``url``."""
    keys = [key for key in signing_keys if key]
    if not token or not keys:
        raise InvalidQStashSignature("missing")
    claims = _claims(token, keys)
    _check_claims(claims, url, time.time() if now is None else now)
    digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=")
    claimed = claims.get("body")
    if not isinstance(claimed, str) or not hmac.compare_digest(
        claimed.rstrip("=").encode(), digest
    ):
        raise InvalidQStashSignature("body")


def _check_claims(claims: dict[str, Any], url: str, current: float) -> None:
    exp, nbf = claims.get("exp"), claims.get("nbf")
    if claims.get("iss") != ISSUER:
        raise InvalidQStashSignature("issuer")
    sub = claims.get("sub")
    if sub != url:
        raise InvalidQStashSignature("subject", sub if isinstance(sub, str) else None)
    if not isinstance(exp, int | float) or not isinstance(nbf, int | float):
        raise InvalidQStashSignature("malformed")
    if current > exp + CLOCK_SKEW_SECONDS:
        raise InvalidQStashSignature("expired")
    if current < nbf - CLOCK_SKEW_SECONDS:
        raise InvalidQStashSignature("not_yet_valid")
    if exp - nbf > MAX_LIFETIME_SECONDS:
        raise InvalidQStashSignature("lifetime")
