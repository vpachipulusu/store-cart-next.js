"""Pure helpers of the invitation service (KAN-62); the flows run on Postgres in
``tests/api/test_invitations_e2e.py``."""

import pytest

from app.services.invitations import (
    MAX_EMAIL_ORG_NAME,
    InvalidEmail,
    canonical_email,
    email_safe_name,
    normalize_email,
)


def test_canonical_email_trims_and_lowercases():
    assert canonical_email("  New@Example.COM ") == "new@example.com"


def test_canonical_email_composes_unicode_first():
    decomposed = "jose\u0301@example.com"  # e + combining acute accent
    composed = "jos\u00e9@example.com"

    assert canonical_email(decomposed) == canonical_email(composed) == composed


@pytest.mark.parametrize(
    "raw", ["no-at-sign", "@example.com", "a@", "a b@example.com", "a\u200b@x.io"]
)
def test_normalize_email_rejects_unusable_addresses(raw):
    with pytest.raises(InvalidEmail):
        normalize_email(raw)


def test_normalize_email_rejects_overlong_addresses():
    with pytest.raises(InvalidEmail):
        normalize_email(f"{'a' * 250}@example.com")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Acme Shop", "Acme Shop"),
        (
            "Acme\nVerify your card at evil.example",
            "Acme Verify your card at evil.example",
        ),
        ("Acme\u202e\u200bShop\t\r", "Acme Shop"),
        ("  lots   of   space  ", "lots of space"),
    ],
)
def test_email_safe_name_is_one_clean_line(name, expected):
    assert email_safe_name(name) == expected


def test_email_safe_name_is_capped():
    cleaned = email_safe_name("x" * 200)

    assert len(cleaned) == MAX_EMAIL_ORG_NAME
    assert cleaned.endswith("…")
