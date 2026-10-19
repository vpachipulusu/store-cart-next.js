"""Store settings row of one store database (KAN-82, KAN-83). No business rules.

The table holds exactly one row (``0005``). Takes the ``AsyncSession`` of one store and
never commits. There is no ORM model for store tables: explicit SQL, bound parameters.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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


class StoreSettingsRepository(BaseRepository):
    async def get(self) -> StoreSettingsRow:
        row = (await self._session.execute(text(_SELECT))).mappings().one()
        return StoreSettingsRow(**row)

    async def update(self, changes: Mapping[str, Any]) -> StoreSettingsRow:
        """Apply ``changes`` (keys from ``SETTING_COLUMNS``) and return the new row."""
        unknown = set(changes) - set(SETTING_COLUMNS)
        if unknown:
            raise ValueError("Unknown store setting")
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
