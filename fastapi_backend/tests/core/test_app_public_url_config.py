"""APP_PUBLIC_URL (KAN-62): the origin used for links in emails."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)


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
