import pytest

from app.repositories.admin_stores import _escape_like

BACKSLASH = chr(92)


@pytest.mark.parametrize(
    ("term", "escaped"),
    [
        ("plain", "plain"),
        ("50%", "50" + BACKSLASH + "%"),
        ("a_b", "a" + BACKSLASH + "_b"),
        ("a" + BACKSLASH + "b", "a" + BACKSLASH * 2 + "b"),
    ],
)
def test_like_wildcards_and_backslashes_are_escaped(term, escaped):
    assert _escape_like(term) == escaped
