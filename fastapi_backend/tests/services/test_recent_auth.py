import pytest

from app.core.config import settings
from app.services.auth import REAUTH_MAX_AGE_SECONDS, is_recent_auth

NOW = 1_000_000.0
SKEW = 10


@pytest.fixture(autouse=True)
def fixed_skew(monkeypatch):
    monkeypatch.setattr(settings, "FIREBASE_CLOCK_SKEW_SECONDS", SKEW)


@pytest.mark.parametrize(
    "age,expected",
    [
        (-SKEW, True),
        (-SKEW - 1, False),
        (-1, True),
        (0, True),
        (REAUTH_MAX_AGE_SECONDS, True),
        (REAUTH_MAX_AGE_SECONDS + 1, False),
    ],
)
def test_freshness_edges(age, expected):
    assert is_recent_auth(NOW - age, now=NOW) is expected


def test_zero_skew_rejects_any_future_auth_time(monkeypatch):
    monkeypatch.setattr(settings, "FIREBASE_CLOCK_SKEW_SECONDS", 0)
    assert is_recent_auth(NOW, now=NOW) is True
    assert is_recent_auth(NOW + 1, now=NOW) is False


def test_defaults_to_the_wall_clock(monkeypatch):
    monkeypatch.setattr("app.services.auth.time.time", lambda: NOW)
    assert is_recent_auth(NOW - 5) is True
    assert is_recent_auth(NOW - 400) is False
