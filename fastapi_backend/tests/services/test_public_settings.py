"""Parity between the backend currency allowlist and the admin page's list (KAN-205)."""

import re
from pathlib import Path

from app.services.public_settings import DEFAULT_CURRENCY, SUPPORTED_CURRENCIES

CURRENCIES_TS = (
    Path(__file__).resolve().parents[3]
    / "nextjs-frontend"
    / "src"
    / "config"
    / "currencies.ts"
)
NINE_CODES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "INR"}


def frontend_codes() -> set[str]:
    source = CURRENCIES_TS.read_text(encoding="utf-8")
    return set(re.findall(r"\{\s*code:\s*'([A-Z]{3})'", source))


def test_supported_currencies_match_the_admin_page_list() -> None:
    assert frontend_codes() == set(SUPPORTED_CURRENCIES)


def test_supported_currencies_are_the_nine_known_codes() -> None:
    assert set(SUPPORTED_CURRENCIES) == NINE_CODES


def test_default_currency_is_supported() -> None:
    assert DEFAULT_CURRENCY in SUPPORTED_CURRENCIES
