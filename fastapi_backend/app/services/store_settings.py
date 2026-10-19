"""Store settings: shipping and tax (KAN-82, KAN-83). No FastAPI imports.

Works on the ``AsyncSession`` of one store (opened by ``store_sessions``) and owns the
transaction: ``update`` validates, writes and commits once. Validation here mirrors the
check constraints of ``0006`` so the client gets a curated 422 instead of a database error.
"""

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.store_settings import (
    SETTING_COLUMNS,
    StoreSettingsRepository,
    StoreSettingsRow,
)
from app.services.store_totals import TotalsSettings

logger = logging.getLogger(__name__)

MAX_AMOUNT_MINOR = 100_000_000_000
MAX_TAX_RATE_BPS = 10_000


class InvalidStoreSettings(Exception):
    """The settings input is not acceptable (message is safe to show)."""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_amount(value: object, *, minimum: int, label: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= MAX_AMOUNT_MINOR
    ):
        raise InvalidStoreSettings(
            f"{label} must be a whole number between {minimum} and {MAX_AMOUNT_MINOR}"
        )


def validate_changes(changes: Mapping[str, Any]) -> None:
    if set(changes) - set(SETTING_COLUMNS):
        raise InvalidStoreSettings("Unknown setting")
    if "shipping_flat_rate_minor" in changes:
        _check_amount(
            changes["shipping_flat_rate_minor"], minimum=0, label="Flat shipping rate"
        )
    threshold = changes.get("free_shipping_threshold_minor")
    if threshold is not None:
        _check_amount(threshold, minimum=1, label="Free shipping threshold")
    if "tax_rate_bps" in changes:
        rate = changes["tax_rate_bps"]
        if not _is_int(rate) or not 0 <= rate <= MAX_TAX_RATE_BPS:
            raise InvalidStoreSettings(
                "Tax rate must be a whole number of basis points "
                f"from 0 to {MAX_TAX_RATE_BPS}"
            )
    if "prices_include_tax" in changes and not isinstance(
        changes["prices_include_tax"], bool
    ):
        raise InvalidStoreSettings("Prices include tax must be true or false")


def totals_settings(row: StoreSettingsRow) -> TotalsSettings:
    """The part of the settings the totals calculation needs."""
    return TotalsSettings(
        shipping_flat_rate_minor=row.shipping_flat_rate_minor,
        free_shipping_threshold_minor=row.free_shipping_threshold_minor,
        tax_rate_bps=row.tax_rate_bps,
        prices_include_tax=row.prices_include_tax,
    )


class StoreSettingsService:
    def __init__(
        self, repository: StoreSettingsRepository, session: AsyncSession
    ) -> None:
        self._repository = repository
        self._session = session

    async def get(self) -> StoreSettingsRow:
        return await self._repository.get()

    async def totals_settings(self) -> TotalsSettings:
        """Settings for ``compute_totals`` (what the order flow calls)."""
        return totals_settings(await self._repository.get())

    async def update(self, changes: Mapping[str, Any]) -> StoreSettingsRow:
        """Apply the sent fields only; an empty change returns the current row."""
        validate_changes(changes)
        if not changes:
            return await self._repository.get()
        try:
            row = await self._repository.update(changes)
            await self._session.commit()
        except (IntegrityError, DataError):
            await self._session.rollback()
            # The checks above mirror the constraints, so reaching here is a validation gap.
            logger.exception("store settings rejected by the database")
            raise InvalidStoreSettings("The settings could not be saved") from None
        except BaseException:
            # Outages, deadlocks and cancellation are not the client's fault: roll back and let them propagate.
            await self._session.rollback()
            raise
        return row
