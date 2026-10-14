import hashlib
import hmac

import pytest

from app.core.stripe_signature import (
    InvalidSignature,
    compute_signature,
    verify_signature,
)

SECRET = "whsec_test_only_not_a_real_secret"
BODY = b'{"id":"evt_1","type":"customer.subscription.updated"}'
NOW = 1_800_000_000


def header(timestamp: int = NOW, *signatures: str) -> str:
    sigs = signatures or (compute_signature(SECRET, timestamp, BODY),)
    return f"t={timestamp}," + ",".join(f"v1={s}" for s in sigs)


def test_compute_signature_matches_stripes_documented_scheme():
    expected = hmac.new(SECRET.encode(), b"1800000000." + BODY, hashlib.sha256)

    assert compute_signature(SECRET, NOW, BODY) == expected.hexdigest()


def test_accepts_a_valid_signature():
    verify_signature(BODY, header(), SECRET, now=NOW)


def test_accepts_when_any_v1_signature_matches():
    good = compute_signature(SECRET, NOW, BODY)

    verify_signature(BODY, header(NOW, "0" * 64, good), SECRET, now=NOW)


def test_ignores_other_schemes_in_the_header():
    good = compute_signature(SECRET, NOW, BODY)

    verify_signature(BODY, f"t={NOW},v0=abc,v1={good}", SECRET, now=NOW)


@pytest.mark.parametrize("bad_header", [None, "", "garbage", "t=abc,v1=ff", "v1=ff"])
def test_rejects_missing_or_malformed_header(bad_header):
    with pytest.raises(InvalidSignature):
        verify_signature(BODY, bad_header, SECRET, now=NOW)


def test_rejects_header_without_a_v1_signature():
    with pytest.raises(InvalidSignature):
        verify_signature(BODY, f"t={NOW},v0=abc", SECRET, now=NOW)


def test_rejects_a_tampered_body():
    with pytest.raises(InvalidSignature):
        verify_signature(BODY + b" ", header(), SECRET, now=NOW)


def test_rejects_a_signature_made_with_another_secret():
    forged = compute_signature("whsec_other", NOW, BODY)

    with pytest.raises(InvalidSignature):
        verify_signature(BODY, header(NOW, forged), SECRET, now=NOW)


def test_rejects_a_stale_timestamp():
    with pytest.raises(InvalidSignature):
        verify_signature(BODY, header(), SECRET, now=NOW + 301)


def test_rejects_a_timestamp_from_the_future():
    with pytest.raises(InvalidSignature):
        verify_signature(BODY, header(), SECRET, now=NOW - 301)


def test_accepts_a_timestamp_at_the_tolerance_edge():
    verify_signature(BODY, header(), SECRET, now=NOW + 300)


def test_rejects_when_the_secret_is_empty():
    with pytest.raises(InvalidSignature):
        verify_signature(BODY, header(), "", now=NOW)


def test_uses_the_current_time_by_default():
    import time

    current = int(time.time())

    verify_signature(
        BODY, header(current, compute_signature(SECRET, current, BODY)), SECRET
    )


def test_rejects_a_non_ascii_signature_without_raising_a_type_error():
    with pytest.raises(InvalidSignature):
        verify_signature(BODY, f"t={NOW},v1=\u00e9", SECRET, now=NOW)
