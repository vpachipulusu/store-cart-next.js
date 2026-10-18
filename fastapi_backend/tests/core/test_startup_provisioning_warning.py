"""create_app warns by name when store provisioning settings are missing (KAN-248)."""

import pytest

from app.core.config import settings
from app.main import create_app


def test_warns_with_the_missing_names_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unconfigured = settings.model_copy(
        update={
            "ENVIRONMENT": "production",
            "VERCEL_ENV": None,
            "QSTASH_TOKEN": None,
            "STORE_DB_PROVIDER": "local",
        }
    )
    monkeypatch.setattr("app.main.settings", unconfigured)

    create_app()

    out = capsys.readouterr().out
    assert "store provisioning is not configured" in out
    assert "QSTASH_TOKEN" in out and "STORE_DB_PROVIDER" in out


def test_is_quiet_when_relaxed(capsys: pytest.CaptureFixture[str]) -> None:
    create_app()

    assert "store provisioning is not configured" not in capsys.readouterr().out
