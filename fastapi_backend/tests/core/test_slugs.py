import pytest

from app.core.slugs import (
    RESERVED_SLUGS,
    InvalidSlug,
    ReservedSlug,
    normalize_slug,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my-store", "my-store"),
        ("MyStore", "mystore"),
        ("abc", "abc"),
        ("a1-b2-c3", "a1-b2-c3"),
        ("123", "123"),
        ("a" * 63, "a" * 63),
    ],
)
def test_accepts_and_lowercases_valid_slugs(raw: str, expected: str) -> None:
    assert normalize_slug(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ab",
        "a" * 64,
        "-abc",
        "abc-",
        "a--b",
        "xn--abc",
        "my store",
        "my_store",
        "my.store",
        "store\n",
        "café",
        "Kelvin",  # Kelvin sign would lower-case to ASCII "k"
        "../etc",
        "a/b",
    ],
)
def test_rejects_malformed_slugs(raw: str) -> None:
    with pytest.raises(InvalidSlug):
        normalize_slug(raw)


@pytest.mark.parametrize("raw", ["www", "admin", "api", "app", "WWW", "Admin"])
def test_rejects_reserved_slugs_in_any_case(raw: str) -> None:
    with pytest.raises(ReservedSlug):
        normalize_slug(raw)


def test_reserved_list_covers_required_and_obvious_names() -> None:
    required = {
        "www",
        "admin",
        "api",
        "app",
        "mail",
        "ftp",
        "static",
        "assets",
        "cdn",
        "dashboard",
        "help",
        "support",
        "blog",
        "status",
    }
    assert required <= RESERVED_SLUGS
