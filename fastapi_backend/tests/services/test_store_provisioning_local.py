"""LocalDatabaseProvisioner against a fake engine, plus factory and settings (KAN-55).

These run in CI. The real-Postgres counterpart is test_store_provisioning_e2e.py.
"""

import logging

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.services.store_provisioning import (
    InvalidStoreId,
    LocalDatabaseProvisioner,
    NeonDatabaseProvisioner,
    ProvisionerNotConfigured,
    ProvisioningFailed,
    database_name_for,
    get_database_provisioner,
)
from tests.fakes_provisioning import API_KEY, FakeEngine

STORE_ID = "clx1abcd2efgh3ijkl4mnop5"
NAME = f"store_{STORE_ID}"


async def test_create_runs_quoted_create_database_then_the_store_role_sql() -> None:
    engine = FakeEngine()

    uri = await LocalDatabaseProvisioner(engine.as_engine()).create_database(STORE_ID)

    assert f'CREATE DATABASE "{NAME}"' in engine.statements
    assert engine.statements[-4:] == [
        f"CREATE ROLE {NAME} PASSWORD <redacted>",
        f'GRANT "{NAME}" TO CURRENT_USER',
        f'ALTER DATABASE "{NAME}" OWNER TO "{NAME}"',
        f'REVOKE CONNECT, TEMPORARY ON DATABASE "{NAME}" FROM PUBLIC',
    ]
    assert engine.databases == {NAME}
    assert engine.owners == {NAME: NAME}
    assert set(engine.isolation_levels) == {"AUTOCOMMIT"}
    password = engine.roles[NAME]
    assert uri == f"postgresql+asyncpg://{NAME}:{password}@db.local:5432/{NAME}"
    assert "s3cret" not in uri


async def test_create_is_idempotent_when_database_exists_and_rotates() -> None:
    engine = FakeEngine(databases=(NAME,))
    engine.roles[NAME] = "old-password"

    uri = await LocalDatabaseProvisioner(engine.as_engine()).create_database(STORE_ID)

    assert not [s for s in engine.statements if s.startswith("CREATE")]
    assert f"ALTER ROLE {NAME} PASSWORD <redacted>" in engine.statements
    assert engine.roles[NAME] != "old-password"
    assert uri.endswith(f"/{NAME}")


async def test_role_sql_failure_carries_no_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = FakeEngine()
    engine.fail.add("role")

    with caplog.at_level(logging.DEBUG), pytest.raises(ProvisioningFailed) as caught:
        await LocalDatabaseProvisioner(engine.as_engine()).create_database(STORE_ID)

    assert "s3cret" not in f"{caught.value!s} {caplog.text}"
    assert "PASSWORD" not in caplog.text
    assert caught.value.__cause__ is None


async def test_create_survives_a_concurrent_creator() -> None:
    engine = FakeEngine()
    engine.fail.add("create")
    engine.race_on_create = True

    uri = await LocalDatabaseProvisioner(engine.as_engine()).create_database(STORE_ID)

    assert uri.endswith(f"/{NAME}")


async def test_create_failure_carries_no_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = FakeEngine()
    engine.fail.add("create")

    with caplog.at_level(logging.DEBUG), pytest.raises(ProvisioningFailed) as caught:
        await LocalDatabaseProvisioner(engine.as_engine()).create_database(STORE_ID)

    assert "s3cret" not in f"{caught.value!s} {caplog.text}"
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("error", [ConnectionRefusedError("x"), OSError("reset")])
async def test_connection_errors_are_wrapped(error: OSError) -> None:
    engine = FakeEngine()
    engine.connect_error = error
    provisioner = LocalDatabaseProvisioner(engine.as_engine())

    with pytest.raises(ProvisioningFailed):
        await provisioner.create_database(STORE_ID)
    with pytest.raises(ProvisioningFailed):
        await provisioner.database_exists(STORE_ID)
    with pytest.raises(ProvisioningFailed):
        await provisioner.delete_database(STORE_ID)


async def test_exists_failure_is_wrapped() -> None:
    engine = FakeEngine()
    engine.fail.add("select")

    with pytest.raises(ProvisioningFailed):
        await LocalDatabaseProvisioner(engine.as_engine()).database_exists(STORE_ID)


async def test_exists_reports_presence() -> None:
    provisioner = LocalDatabaseProvisioner(FakeEngine(databases=(NAME,)).as_engine())

    assert await provisioner.database_exists(STORE_ID) is True
    assert await provisioner.database_exists("clx9zzzzzzzzzzzzzzzzzzzz") is False


async def test_delete_drops_quoted_name_and_missing_is_fine() -> None:
    engine = FakeEngine(databases=(NAME,))
    provisioner = LocalDatabaseProvisioner(engine.as_engine())

    await provisioner.delete_database(STORE_ID)
    await provisioner.delete_database(STORE_ID)

    assert engine.statements[:2] == [
        f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)',
        f'DROP ROLE IF EXISTS "{NAME}"',
    ]
    assert engine.databases == set()


async def test_delete_drops_the_store_role() -> None:
    engine = FakeEngine()
    provisioner = LocalDatabaseProvisioner(engine.as_engine())
    await provisioner.create_database(STORE_ID)

    await provisioner.delete_database(STORE_ID)

    assert engine.roles == {}


async def test_delete_failure_is_wrapped() -> None:
    engine = FakeEngine()
    engine.fail.add("drop")

    with pytest.raises(ProvisioningFailed):
        await LocalDatabaseProvisioner(engine.as_engine()).delete_database(STORE_ID)


async def test_injection_is_rejected_before_any_statement() -> None:
    engine = FakeEngine()

    with pytest.raises(InvalidStoreId):
        await LocalDatabaseProvisioner(engine.as_engine()).create_database(
            'x"; --injected'
        )

    assert engine.statements == []


def test_invalid_store_id_message_cannot_forge_log_lines() -> None:
    with pytest.raises(InvalidStoreId) as caught:
        database_name_for("bad\nERROR forged line")

    assert "\n" not in str(caught.value)
    assert "\\n" in str(caught.value)


def settings(**overrides: object) -> Settings:
    return Settings(  # type: ignore[call-arg]
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", **overrides
    )


def neon_settings(**overrides: object) -> Settings:
    return settings(
        STORE_DB_PROVIDER="neon",
        NEON_API_KEY=SecretStr(API_KEY),
        NEON_PROJECT_ID="proj-1",
        NEON_BRANCH_ID="br-1",
        NEON_ROLE_NAME="owner",
        **overrides,
    )


def test_factory_defaults_to_local_in_test_environment() -> None:
    engine = FakeEngine().as_engine()

    assert isinstance(
        get_database_provisioner(settings(), engine), LocalDatabaseProvisioner
    )


@pytest.mark.parametrize(
    "update", [{"ENVIRONMENT": "production"}, {"VERCEL_ENV": "production"}]
)
def test_factory_refuses_local_outside_development(update: dict[str, str]) -> None:
    deployed = settings().model_copy(update=update)

    with pytest.raises(ProvisionerNotConfigured) as caught:
        get_database_provisioner(deployed, FakeEngine().as_engine())

    assert "development only" in str(caught.value)
    assert "neon" in str(caught.value)


def test_factory_allows_local_on_vercel_preview() -> None:
    preview = settings().model_copy(
        update={"ENVIRONMENT": "production", "VERCEL_ENV": "preview"}
    )

    assert isinstance(
        get_database_provisioner(preview, FakeEngine().as_engine()),
        LocalDatabaseProvisioner,
    )


def test_factory_builds_neon_in_production() -> None:
    deployed = neon_settings().model_copy(update={"ENVIRONMENT": "production"})

    assert isinstance(get_database_provisioner(deployed), NeonDatabaseProvisioner)


def test_factory_names_missing_neon_variables_without_values() -> None:
    incomplete = settings(STORE_DB_PROVIDER="neon", NEON_API_KEY=SecretStr(API_KEY))

    with pytest.raises(ProvisionerNotConfigured) as caught:
        get_database_provisioner(incomplete)

    assert caught.value.missing == (
        "NEON_PROJECT_ID",
        "NEON_BRANCH_ID",
        "NEON_ROLE_NAME",
    )
    assert API_KEY not in str(caught.value)


def test_settings_reject_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        settings(STORE_DB_PROVIDER="mongo")


@pytest.mark.parametrize(
    "url",
    [
        "http://console.neon.tech/api/v2",
        "https://evil.example/api/v2",
        "https://neon.tech.evil.example/api/v2",
        "https://console.neon.tech.evil.example/api/v2",
        "ftp://console.neon.tech/api/v2",
    ],
)
def test_settings_reject_unsafe_neon_base_url(url: str) -> None:
    with pytest.raises(ValidationError):
        settings(NEON_API_BASE_URL=url)


def test_settings_accept_default_neon_base_url() -> None:
    assert settings().NEON_API_BASE_URL == "https://console.neon.tech/api/v2"
