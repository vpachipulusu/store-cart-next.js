import pytest

from app.core.config import settings
from app.core.firebase import AuthenticationFailed
from app.services.auth import REAUTH_MAX_AGE_SECONDS, AuthService, is_recent_auth

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


class _Identity:
    def __init__(self, auth_time):
        self.claims = {
            "uid": "u",
            "email": "a@b.co",
            "email_verified": True,
            "auth_time": auth_time,
        }

    async def verify_id_token(self, token):
        return self.claims


@pytest.mark.parametrize(
    "offset,accepted", [(SKEW, True), (SKEW + 1, False), (-300, True), (-301, False)]
)
async def test_prepare_login_uses_the_shared_freshness_rule(
    monkeypatch, offset, accepted
):
    monkeypatch.setattr("app.services.auth.time.time", lambda: NOW)
    service = AuthService(_Identity(int(NOW) + offset), None, None)  # type: ignore[arg-type]
    if accepted:
        assert (await service.prepare_login("token")).uid == "u"
    else:
        with pytest.raises(AuthenticationFailed):
            await service.prepare_login("token")
