import pytest
from pydantic import ValidationError

from app.core.config import Settings

ACCOUNT = "0123456789abcdef0123456789abcdef"
R2_NAMES = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_BASE_URL",
)
VALID = {
    "R2_ACCOUNT_ID": ACCOUNT,
    "R2_ACCESS_KEY_ID": "key-id",
    "R2_SECRET_ACCESS_KEY": "super-secret-value",
    "R2_BUCKET_NAME": "media",
    "R2_PUBLIC_BASE_URL": "https://media.example.com",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in R2_NAMES:
        monkeypatch.delenv(name, raising=False)


def configure(monkeypatch, **overrides):
    for name, value in {**VALID, **overrides}.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_all_unset_is_allowed():
    settings = Settings(_env_file=None)

    assert settings.R2_ACCOUNT_ID is None
    assert settings.R2_SECRET_ACCESS_KEY is None


def test_complete_configuration_is_accepted_and_secret_is_masked(monkeypatch):
    settings = configure(monkeypatch)

    assert settings.R2_BUCKET_NAME == "media"
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)


@pytest.mark.parametrize("missing", R2_NAMES)
def test_partial_configuration_is_rejected(monkeypatch, missing):
    for name, value in VALID.items():
        if name != missing:
            monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match="must be set together"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "account", ["short", ACCOUNT + "0", "g" * 32, "a.b/" + "0" * 28]
)
def test_account_id_must_be_32_hex_characters(monkeypatch, account):
    with pytest.raises(ValidationError, match="32 hexadecimal"):
        configure(monkeypatch, R2_ACCOUNT_ID=account)


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.com",
        "media.example.com",
        "https://media.example.com/?x=1",
        "https://media.example.com/#frag",
        "https://user:pw@media.example.com",
        "https://",
    ],
)
def test_public_base_url_must_be_plain_https(monkeypatch, url):
    with pytest.raises(ValidationError, match="R2_PUBLIC_BASE_URL"):
        configure(monkeypatch, R2_PUBLIC_BASE_URL=url)


@pytest.mark.parametrize("name", R2_NAMES)
def test_empty_value_counts_as_unset_and_is_rejected_as_partial(monkeypatch, name):
    with pytest.raises(ValidationError, match="must be set together"):
        configure(monkeypatch, **{name: ""})


@pytest.mark.parametrize("bucket", ["a", "UPPER", "has/slash", "..", "-lead", "a b"])
def test_bucket_name_must_be_a_valid_bucket_name(monkeypatch, bucket):
    with pytest.raises(ValidationError, match="R2_BUCKET_NAME"):
        configure(monkeypatch, R2_BUCKET_NAME=bucket)
