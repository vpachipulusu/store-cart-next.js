import base64

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.store_crypto import StoreSecretCodec, StoreSecretUnavailable, generate_key

DSN = "postgresql://user:hunter2@db.example.invalid/store?sslmode=require"


def test_round_trip_is_not_plaintext_and_nonce_is_random():
    codec = StoreSecretCodec(generate_key())
    first = codec.encrypt(DSN, "s1")
    assert "hunter2" not in first
    assert first != codec.encrypt(DSN, "s1")
    assert codec.decrypt(first, "s1") == DSN


def test_wrong_key_fails_safely():
    envelope = StoreSecretCodec(generate_key()).encrypt(DSN, "s1")
    with pytest.raises(StoreSecretUnavailable):
        StoreSecretCodec(generate_key()).decrypt(envelope, "s1")


def test_tampering_and_malformed_envelopes_fail_safely():
    codec = StoreSecretCodec(generate_key())
    version, key_id, payload = codec.encrypt(DSN, "s1").split(".")
    raw = bytearray(base64.urlsafe_b64decode(payload))
    raw[-1] ^= 1
    flipped = base64.urlsafe_b64encode(bytes(raw)).decode()
    for bad in (
        f"{version}.{key_id}.{flipped}",
        f"v2.{key_id}.{payload}",
        f"{version}.{key_id}.{payload[:10]}",
        f"{version}.{key_id}.",
        "garbage",
        "",
        f"{version}.{key_id}.%%%",
    ):
        with pytest.raises(StoreSecretUnavailable):
            codec.decrypt(bad, "s1")


def test_ciphertext_is_bound_to_its_store():
    codec = StoreSecretCodec(generate_key())
    with pytest.raises(StoreSecretUnavailable):
        codec.decrypt(codec.encrypt(DSN, "s1"), "s2")


def test_rotation_keeps_old_rows_readable_then_reencrypts():
    old, new = generate_key(), generate_key()
    envelope = StoreSecretCodec(old).encrypt(DSN, "s1")
    codec = StoreSecretCodec(new, [old])
    assert codec.decrypt(envelope, "s1") == DSN
    assert codec.needs_rotation(envelope)
    rotated = codec.rotate(envelope, "s1")
    assert not codec.needs_rotation(rotated)
    assert StoreSecretCodec(new).decrypt(rotated, "s1") == DSN
    assert codec.needs_rotation("garbage")


@pytest.mark.parametrize(
    "key",
    [None, "", "not base64 !!", base64.urlsafe_b64encode(b"short").decode(), "é"],
)
def test_invalid_keys_rejected(key):
    with pytest.raises(StoreSecretUnavailable):
        StoreSecretCodec(key)
    with pytest.raises(StoreSecretUnavailable):
        StoreSecretCodec(generate_key(), [key or ""])


def test_settings_validate_key_at_startup(monkeypatch):
    key = generate_key()
    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY", key)
    cfg = Settings(_env_file=None)
    assert key not in repr(cfg)

    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY", "bad-key-value")
    with pytest.raises(ValidationError, match="base64url encoded 32 byte keys"):
        Settings(_env_file=None)

    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY", key)
    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY_PREVIOUS", f"{generate_key()}, bad")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_previous_key_requires_current(monkeypatch):
    monkeypatch.delenv("STORE_DB_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY_PREVIOUS", generate_key())
    with pytest.raises(ValidationError, match="STORE_DB_ENCRYPTION_KEY is required"):
        Settings(_env_file=None)


def test_key_is_required_in_production(monkeypatch):
    monkeypatch.delenv("STORE_DB_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://x.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "t")
    with pytest.raises(ValidationError, match="STORE_DB_ENCRYPTION_KEY must be set"):
        Settings(_env_file=None)
