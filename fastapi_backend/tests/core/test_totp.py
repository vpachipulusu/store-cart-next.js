import pytest
from cryptography.fernet import Fernet

from app.core.totp import (
    TotpCodec,
    TotpUnavailable,
    generate_secret,
    provisioning_uri,
    token_at,
    verify_token,
)


def test_rfc_6238_sha1_vector_truncated_to_six_digits():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert token_at(secret, 59) == "287082"


def test_verification_accepts_adjacent_steps_only():
    secret = generate_secret()
    assert verify_token(secret, token_at(secret, 90), 120)
    assert verify_token(secret, token_at(secret, 120), 120)
    assert verify_token(secret, token_at(secret, 150), 120)
    assert not verify_token(secret, token_at(secret, 60), 120)


@pytest.mark.parametrize("token", ["12345", "1234567", "abcdef", "１２３４５６"])
def test_invalid_token_format_is_rejected(token):
    assert not verify_token(generate_secret(), token)


def test_secret_is_encrypted_and_wrong_key_fails_closed():
    codec = TotpCodec(Fernet.generate_key().decode())
    secret = generate_secret()
    ciphertext = codec.encrypt(secret)
    assert secret not in ciphertext
    assert codec.decrypt(ciphertext) == secret
    with pytest.raises(TotpUnavailable):
        TotpCodec(Fernet.generate_key().decode()).decrypt(ciphertext)


@pytest.mark.parametrize("key", [None, "invalid", "é"])
def test_missing_or_invalid_key_fails_closed(key):
    with pytest.raises(TotpUnavailable):
        TotpCodec(key)


def test_uri_encodes_user_label():
    uri = provisioning_uri("TEST", "ada+test@example.com")
    assert "StoreCart%3Aada%2Btest%40example.com" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri
