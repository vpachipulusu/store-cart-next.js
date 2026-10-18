"""Provisioning settings check behind /health/ready (KAN-248): names only, never values."""

import pytest
from pydantic import SecretStr

from app.core.config import Settings, settings
from app.services.provisioning_readiness import check_provisioning_settings

SECRET_VALUE = "super-secret-value-must-never-appear"


def production(**overrides: object) -> Settings:
    """A production-like Settings with every provisioning variable present."""
    base: dict[str, object] = {
        "ENVIRONMENT": "production",
        "VERCEL_ENV": None,
        "QSTASH_TOKEN": SecretStr(SECRET_VALUE),
        "QSTASH_CURRENT_SIGNING_KEY": SecretStr(SECRET_VALUE),
        "QSTASH_NEXT_SIGNING_KEY": SecretStr(SECRET_VALUE),
        "PROVISIONING_BASE_URL": "https://app.example.com",
        "STORE_DB_PROVIDER": "neon",
        "NEON_API_KEY": SecretStr(SECRET_VALUE),
        "NEON_PROJECT_ID": "project",
        "NEON_BRANCH_ID": "branch",
        "NEON_ROLE_NAME": "role",
        "STORE_DB_ENCRYPTION_KEY": SecretStr(SECRET_VALUE),
    }
    return settings.model_copy(update={**base, **overrides})


def test_complete_production_configuration_is_ready() -> None:
    result = check_provisioning_settings(production())

    assert result.ready is True
    assert result.missing == ()


@pytest.mark.parametrize(
    ("override", "name"),
    [
        ({"QSTASH_TOKEN": None}, "QSTASH_TOKEN"),
        ({"PROVISIONING_BASE_URL": None}, "PROVISIONING_BASE_URL"),
        ({"STORE_DB_ENCRYPTION_KEY": None}, "STORE_DB_ENCRYPTION_KEY"),
        ({"NEON_API_KEY": None}, "NEON_API_KEY"),
        ({"NEON_PROJECT_ID": None}, "NEON_PROJECT_ID"),
        ({"NEON_BRANCH_ID": ""}, "NEON_BRANCH_ID"),
        ({"NEON_ROLE_NAME": None}, "NEON_ROLE_NAME"),
        ({"STORE_DB_PROVIDER": "local"}, "STORE_DB_PROVIDER"),
    ],
)
def test_reports_the_missing_setting_by_name(
    override: dict[str, object], name: str
) -> None:
    result = check_provisioning_settings(production(**override))

    assert result.ready is False
    assert result.missing == (name,)


def test_needs_at_least_one_signing_key() -> None:
    result = check_provisioning_settings(
        production(QSTASH_CURRENT_SIGNING_KEY=None, QSTASH_NEXT_SIGNING_KEY=None)
    )

    assert result.missing == ("QSTASH_CURRENT_SIGNING_KEY",)


def test_one_signing_key_is_enough() -> None:
    assert check_provisioning_settings(
        production(QSTASH_NEXT_SIGNING_KEY=None)
    ).ready


def test_neon_variables_are_not_required_for_the_local_provider_in_development() -> (
    None
):
    result = check_provisioning_settings(
        production(
            ENVIRONMENT="local",
            STORE_DB_PROVIDER="local",
            QSTASH_TOKEN=None,
            PROVISIONING_BASE_URL=None,
            NEON_API_KEY=None,
        )
    )

    assert result.ready is True


def test_result_never_contains_a_value() -> None:
    result = check_provisioning_settings(production(QSTASH_TOKEN=None))

    assert SECRET_VALUE not in repr(result)
    assert "app.example.com" not in repr(result)
