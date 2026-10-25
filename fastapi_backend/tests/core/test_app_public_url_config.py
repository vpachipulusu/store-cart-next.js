"""APP_PUBLIC_URL (KAN-62): the origin used for links in emails."""

import logging

import pytest
from pydantic import ValidationError

from app.api import deps
from app.core.config import Settings
from app.services.email import DisabledEmailSender


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("APP_PUBLIC_URL", "VERCEL_ENV", "RESEND_API_KEY", "EMAIL_FROM"):
        monkeypatch.delenv(name, raising=False)


def test_blank_counts_as_unset(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "")

    assert Settings(_env_file=None).app_public_url == "http://localhost:3000"


@pytest.mark.parametrize(
    ("key", "sender", "missing"),
    [
        ("re_test_placeholder", None, "EMAIL_FROM"),
        ("re_test_placeholder", "  ", "EMAIL_FROM"),
        (None, "team@example.com", "RESEND_API_KEY"),
        ("  ", "x@y.z", "RESEND_API_KEY"),
    ],
)
def test_half_email_config_logs_an_error_and_disables_email(
    monkeypatch, caplog, key, sender, missing
):
    if key is not None:
        monkeypatch.setenv("RESEND_API_KEY", key)
    if sender is not None:
        monkeypatch.setenv("EMAIL_FROM", sender)
    caplog.set_level(logging.ERROR, logger="storecart.config")

    settings = Settings(_env_file=None)  # no exception: startup continues
    monkeypatch.setattr(deps, "settings", settings)
    monkeypatch.setattr(deps, "_email_sender", None)

    assert isinstance(deps.get_email_sender(), DisabledEmailSender)
    [record] = [r for r in caplog.records if r.name == "storecart.config"]
    assert record.levelno == logging.ERROR
    assert record.getMessage() == (
        f"{missing} is not set while the other email setting is: emails are disabled"
    )
    assert "re_test_placeholder" not in caplog.text


@pytest.mark.parametrize(("key", "sender"), [("", ""), (None, None), ("", " ")])
def test_email_unset_or_blank_means_disabled(monkeypatch, key, sender):
    if key is not None:
        monkeypatch.setenv("RESEND_API_KEY", key)
    if sender is not None:
        monkeypatch.setenv("EMAIL_FROM", sender)

    settings = Settings(_env_file=None)

    assert (settings.resend_api_key, settings.email_from) == (None, None)


def test_email_configured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_placeholder")
    monkeypatch.setenv("EMAIL_FROM", " StoreCart <team@example.com> ")

    settings = Settings(_env_file=None)

    assert settings.resend_api_key == "re_test_placeholder"
    assert settings.email_from == "StoreCart <team@example.com>"


def test_unset_falls_back_to_localhost_in_test():
    assert Settings(_env_file=None).app_public_url == "http://localhost:3000"


def test_unset_outside_local_disables_links(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://redis.example.com")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "token")
    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY", "A" * 43)

    assert Settings(_env_file=None).app_public_url is None


@pytest.mark.parametrize("vercel_env", ["preview", "development"])
def test_vercel_preview_gets_no_localhost_fallback(monkeypatch, vercel_env):
    monkeypatch.setenv("VERCEL_ENV", vercel_env)

    assert Settings(_env_file=None).app_public_url is None


def test_https_origin_is_used_without_trailing_slash(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "https://app.example.com/")

    assert Settings(_env_file=None).app_public_url == "https://app.example.com"


def test_http_localhost_is_allowed_in_test(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "http://localhost:3100")

    assert Settings(_env_file=None).app_public_url == "http://localhost:3100"


@pytest.mark.parametrize(
    "value",
    [
        "http://app.example.com",
        "https://app.example.com/path",
        "https://app.example.com?x=1",
        "https://app.example.com#x",
        "https://user:pw@app.example.com",
        "ftp://app.example.com",
        "not a url",
    ],
)
def test_rejects_anything_but_an_https_origin(monkeypatch, value):
    monkeypatch.setenv("APP_PUBLIC_URL", value)

    with pytest.raises(ValidationError, match="APP_PUBLIC_URL"):
        Settings(_env_file=None)
