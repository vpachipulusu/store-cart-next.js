"""The root vercel.json must route QStash callbacks to the backend (KAN-248).

The backend service has no public route of its own (ADR-011): a path reaches it only
through a top-level rewrite placed before the frontend catch-all. Without one, QStash
delivers to the frontend, which answers 404, and a new store stays PROVISIONING forever.
"""

import json
import re
from pathlib import Path

import pytest

from app.services.store_provisioning_job import FAILED_PATH, STEP_PATH

VERCEL_JSON = Path(__file__).resolve().parents[3] / "vercel.json"
BACKEND_SERVICE = "fastapi_backend"


def _rewrites() -> list[dict[str, object]]:
    return json.loads(VERCEL_JSON.read_text(encoding="utf-8"))["rewrites"]


def _destination_service(path: str) -> str | None:
    """The service of the first rewrite whose source matches ``path``."""
    for rule in _rewrites():
        source = str(rule["source"])
        if re.fullmatch(source.replace("(.*)", ".*"), path):
            destination = rule["destination"]
            assert isinstance(destination, dict)
            return str(destination["service"])
    return None


@pytest.mark.parametrize("path", [STEP_PATH, FAILED_PATH])
def test_provisioning_callbacks_reach_the_backend(path: str) -> None:
    assert _destination_service(path) == BACKEND_SERVICE


def test_everything_else_still_reaches_the_frontend() -> None:
    assert _destination_service("/dashboard") == "nextjs-frontend"
    assert _destination_service("/internal-notes") == "nextjs-frontend"


def test_only_the_provisioning_callbacks_are_public() -> None:
    backend_rules = [
        r for r in _rewrites() if r["destination"] == {"service": BACKEND_SERVICE}
    ]
    assert [r["source"] for r in backend_rules] == ["/internal/provisioning/(.*)"]
