"""Store settings row of one store database (KAN-82, KAN-83). No business rules.

The table holds exactly one row (``0006``). Takes the ``AsyncSession`` of one store and
never commits. There is no ORM model for store tables: explicit SQL, bound parameters.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.repositories.base import BaseRepository

# Column names the caller may set; the update statement is built only from this allow-list.
SETTING_COLUMNS = (
    "shipping_flat_rate_minor",
    "free_shipping_threshold_minor",
    "tax_rate_bps",
    "prices_include_tax",
)


@dataclass(frozen=True)
class StoreSettingsRow:
    shipping_flat_rate_minor: int
    free_shipping_threshold_minor: int | None
    tax_rate_bps: int
    prices_include_tax: bool
    updated_at: datetime


_COLUMNS = ", ".join((*SETTING_COLUMNS, "updated_at"))
_SELECT = f"SELECT {_COLUMNS} FROM store_settings"


_ENSURE_ROW = text(
    "INSERT INTO store_settings (id) VALUES (true) ON CONFLICT (id) DO NOTHING"
)


class StoreSettingsRepository(BaseRepository):
    async def _ensure_row(self) -> None:
        """Re-create the singleton row if a support script removed it (the migration seeds it). Writes only."""
        await self._session.execute(_ENSURE_ROW)

    async def get(self) -> StoreSettingsRow:
        """The row, or the defaults when it is missing; a read never writes."""
        row = (await self._session.execute(text(_SELECT))).mappings().one_or_none()
        if row is None:  # the migration seeds it; only a removed row gets here
            return StoreSettingsRow(
                shipping_flat_rate_minor=0,
                free_shipping_threshold_minor=None,
                tax_rate_bps=0,
                prices_include_tax=False,
                updated_at=datetime.now(UTC),
            )
        return StoreSettingsRow(**row)

    async def update(self, changes: Mapping[str, Any]) -> StoreSettingsRow:
        """Apply ``changes`` (keys from ``SETTING_COLUMNS``) and return the new row."""
        unknown = set(changes) - set(SETTING_COLUMNS)
        if unknown:
            raise ValueError("Unknown store setting")
        await self._ensure_row()
        assignments = "".join(f"{column} = :{column}, " for column in changes)
        row = (
            (
                await self._session.execute(
                    text(
                        f"UPDATE store_settings SET {assignments}updated_at = now() "
                        f"RETURNING {_COLUMNS}"
                    ),
                    dict(changes),
                )
            )
            .mappings()
            .one()
        )
        return StoreSettingsRow(**row)
