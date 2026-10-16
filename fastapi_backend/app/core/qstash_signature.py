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
    """The signature header is missing, malformed, expired or does not match."""


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
        raise InvalidQStashSignature
    head, payload, signature = parts
    signing_input = f"{head}.{payload}".encode()
    if not _signed_by_any(signing_input, _b64decode(signature), keys):
        raise InvalidQStashSignature
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
        raise InvalidQStashSignature
    claims = _claims(token, keys)
    current = time.time() if now is None else now
    exp, nbf = claims.get("exp"), claims.get("nbf")
    if (
        claims.get("iss") != ISSUER
        or claims.get("sub") != url
        or not isinstance(exp, int | float)
        or not isinstance(nbf, int | float)
        or current > exp + CLOCK_SKEW_SECONDS
        or current < nbf - CLOCK_SKEW_SECONDS
        or exp - nbf > MAX_LIFETIME_SECONDS
    ):
        raise InvalidQStashSignature
    digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=")
    claimed = claims.get("body")
    if not isinstance(claimed, str) or not hmac.compare_digest(
        claimed.rstrip("=").encode(), digest
    ):
        raise InvalidQStashSignature
