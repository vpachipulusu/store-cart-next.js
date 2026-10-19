"""Store settings service: validation and transaction handling (KAN-82, KAN-83). No database."""

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.repositories.store_settings import StoreSettingsRepository, StoreSettingsRow
from app.services.store_settings import (
    InvalidStoreSettings,
    StoreSettingsService,
    totals_settings,
    validate_changes,
)

ROW = StoreSettingsRow(
    shipping_flat_rate_minor=499,
    free_shipping_threshold_minor=5000,
    tax_rate_bps=2000,
    prices_include_tax=True,
    updated_at=datetime(2026, 10, 19, tzinfo=UTC),
)


def service(repository: AsyncMock, session: AsyncMock) -> StoreSettingsService:
    return StoreSettingsService(cast(StoreSettingsRepository, repository), session)


@pytest.mark.parametrize(
    "changes",
    [
        {"nope": 1},
        {"shipping_flat_rate_minor": -1},
        {"shipping_flat_rate_minor": True},
        {"shipping_flat_rate_minor": 1.5},
        {"free_shipping_threshold_minor": 0},
        {"tax_rate_bps": 10_001},
        {"tax_rate_bps": False},
        {"prices_include_tax": 1},
    ],
)
def test_rejects_invalid_changes(changes: dict[str, Any]) -> None:
    with pytest.raises(InvalidStoreSettings):
        validate_changes(changes)


def test_accepts_the_edges_and_a_cleared_threshold() -> None:
    validate_changes(
        {
            "shipping_flat_rate_minor": 0,
            "free_shipping_threshold_minor": None,
            "tax_rate_bps": 10_000,
            "prices_include_tax": False,
        }
    )


async def test_update_writes_and_commits_once() -> None:
    repository, session = AsyncMock(), AsyncMock()
    repository.update.return_value = ROW

    result = await service(repository, session).update({"tax_rate_bps": 2000})

    assert result is ROW
    repository.update.assert_awaited_once_with({"tax_rate_bps": 2000})
    session.commit.assert_awaited_once()


async def test_an_empty_update_reads_without_writing() -> None:
    repository, session = AsyncMock(), AsyncMock()
    repository.get.return_value = ROW

    result = await service(repository, session).update({})

    assert result is ROW
    repository.update.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_a_constraint_error_rolls_back_and_hides_its_text() -> None:
    repository, session = AsyncMock(), AsyncMock()
    repository.update.side_effect = IntegrityError("stmt", {}, Exception("ck_secret"))

    with pytest.raises(InvalidStoreSettings, match="could not be saved") as raised:
        await service(repository, session).update({"tax_rate_bps": 1})

    session.rollback.assert_awaited_once()
    assert "ck_secret" not in str(raised.value)


async def test_totals_settings_maps_the_row() -> None:
    repository, session = AsyncMock(), AsyncMock()
    repository.get.return_value = ROW

    settings = await service(repository, session).totals_settings()

    assert settings == totals_settings(ROW)
    assert (settings.shipping_flat_rate_minor, settings.tax_rate_bps) == (499, 2000)
    assert settings.free_shipping_threshold_minor == 5000
    assert settings.prices_include_tax is True


async def test_an_outage_rolls_back_and_is_not_reported_as_bad_input() -> None:
    repository, session = AsyncMock(), AsyncMock()
    repository.update.side_effect = OperationalError("stmt", {}, Exception("lost"))

    with pytest.raises(OperationalError):
        await service(repository, session).update({"tax_rate_bps": 1})

    session.rollback.assert_awaited_once()
