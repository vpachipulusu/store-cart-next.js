import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings


def test_totp_key_is_optional_and_routes_fail_closed_when_missing(monkeypatch):
    monkeypatch.delenv("TOTP_ENCRYPTION_KEY", raising=False)
    assert Settings(_env_file=None).TOTP_ENCRYPTION_KEY is None


@pytest.mark.parametrize("key", ["", "invalid", "é"])
def test_invalid_configured_key_rejected_without_disclosing_value(monkeypatch, key):
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", key)
    with pytest.raises(ValidationError, match="must be a valid Fernet key"):
        Settings(_env_file=None)


def test_valid_configured_key_is_masked(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", key)
    settings = Settings(_env_file=None)
    assert key not in repr(settings)
    assert settings.TOTP_ENCRYPTION_KEY.get_secret_value() == key
