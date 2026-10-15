"""Settings that are safe for anyone to read (KAN-205)."""

from typing import Any, Protocol

CURRENCY_KEY = "currency"
# Same default as getCurrencySymbol in nextjs-frontend/src/config/subscriptions.ts.
DEFAULT_CURRENCY = "USD"
# Codes the admin settings page offers (nextjs-frontend/src/config/currencies.ts).
SUPPORTED_CURRENCIES = frozenset(
    {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "INR"}
)


class SettingReader(Protocol):
    async def get_value(self, key: str) -> Any | None: ...


class PublicSettingsService:
    def __init__(self, repository: SettingReader) -> None:
        self._repository = repository

    async def currency(self) -> str:
        """The platform currency as an upper-case supported code.

        A missing row, a non-string value or a code the platform does not support all
        answer the default, so callers always get a usable code.
        """
        stored = await self._repository.get_value(CURRENCY_KEY)
        if not isinstance(stored, str):
            return DEFAULT_CURRENCY
        code = stored.strip().upper()
        return code if code in SUPPORTED_CURRENCIES else DEFAULT_CURRENCY
