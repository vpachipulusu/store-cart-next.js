import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.store_crypto import generate_key


def test_production_requires_auth_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY", generate_key())
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://example.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "test-token")
    monkeypatch.delenv("BACKEND_INTERNAL_KEY", raising=False)
    with pytest.raises(ValidationError, match="Production authentication requires"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_short_internal_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_INTERNAL_KEY", "short")
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_missing_database_url_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

    assert Settings(_env_file=None).DATABASE_URL.endswith("/db")  # type: ignore[call-arg]


@pytest.mark.parametrize("environment", ["production", "preview", "staging"])
def test_deployed_environment_without_upstash_fails_startup(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="UPSTASH_REDIS_REST_URL"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_environment_defaults_to_production_and_requires_upstash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    with pytest.raises(ValidationError, match="UPSTASH_REDIS_REST_TOKEN"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_deployed_environment_with_only_one_upstash_setting_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://x.upstash.io")
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("environment", ["local", "test"])
def test_local_and_test_start_without_upstash(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)

    assert Settings(_env_file=None).UPSTASH_REDIS_REST_URL is None  # type: ignore[call-arg]


def test_production_starts_with_both_upstash_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("STORE_DB_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://x.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "t")

    assert Settings(_env_file=None).ENVIRONMENT == "production"  # type: ignore[call-arg]


@pytest.fixture
def no_upstash(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    return monkeypatch


@pytest.mark.parametrize("vercel_env", ["preview", "development"])
def test_vercel_preview_and_development_start_without_upstash(
    no_upstash: pytest.MonkeyPatch, vercel_env: str
) -> None:
    no_upstash.setenv("VERCEL_ENV", vercel_env)
    no_upstash.delenv("ENVIRONMENT", raising=False)  # defaults to production

    assert Settings(_env_file=None).UPSTASH_REDIS_REST_URL is None  # type: ignore[call-arg]


def test_vercel_production_without_upstash_fails_even_if_environment_is_local(
    no_upstash: pytest.MonkeyPatch,
) -> None:
    no_upstash.setenv("VERCEL_ENV", "production")
    no_upstash.setenv("ENVIRONMENT", "local")

    with pytest.raises(ValidationError, match="UPSTASH_REDIS_REST_URL"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_vercel_production_starts_with_upstash(no_upstash: pytest.MonkeyPatch) -> None:
    no_upstash.setenv("VERCEL_ENV", "production")
    no_upstash.setenv("STORE_DB_ENCRYPTION_KEY", generate_key())
    no_upstash.setenv("UPSTASH_REDIS_REST_URL", "https://x.upstash.io")
    no_upstash.setenv("UPSTASH_REDIS_REST_TOKEN", "t")

    assert Settings(_env_file=None).VERCEL_ENV == "production"  # type: ignore[call-arg]


def test_outside_vercel_the_default_environment_is_strict(
    no_upstash: pytest.MonkeyPatch,
) -> None:
    no_upstash.delenv("VERCEL_ENV", raising=False)
    no_upstash.delenv("ENVIRONMENT", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
