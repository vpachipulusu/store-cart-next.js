"""Stripe webhook signature verification (KAN-44).

Implements Stripe's documented scheme: the ``Stripe-Signature`` header carries a
timestamp ``t`` and one or more ``v1`` HMAC-SHA256 signatures of ``"{t}.{raw body}"``
keyed with the endpoint secret. The body must be the exact bytes Stripe sent.
Nothing here logs or echoes the header, body or secret.
"""

import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300
SCHEME = "v1"


class InvalidSignature(Exception):
    """The signature header is missing, malformed, stale or does not match."""


def _parse_header(header: str) -> tuple[int, list[str]]:
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                raise InvalidSignature from None
        elif key == SCHEME:
            signatures.append(value)
    if timestamp is None or not signatures:
        raise InvalidSignature
    return timestamp, signatures


def compute_signature(secret: str, timestamp: int, payload: bytes) -> str:
    signed = str(timestamp).encode() + b"." + payload
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def verify_signature(
    payload: bytes,
    header: str | None,
    secret: str,
    *,
    now: float | None = None,
    tolerance: int = TOLERANCE_SECONDS,
) -> None:
    """Raise InvalidSignature unless ``header`` signs ``payload`` within ``tolerance``."""
    if not header or not secret:
        raise InvalidSignature
    timestamp, signatures = _parse_header(header)
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance:
        raise InvalidSignature
    expected = compute_signature(secret, timestamp, payload).encode()
    # Bytes, so a non-ASCII candidate cannot raise. Check every candidate without
    # short-circuiting on the first match.
    matches = [
        hmac.compare_digest(expected, candidate.encode()) for candidate in signatures
    ]
    if not any(matches):
        raise InvalidSignature
