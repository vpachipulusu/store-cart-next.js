"""The root vercel.json must route QStash callbacks and Stripe events to the backend (KAN-248, KAN-251).

The backend service has no public route of its own (ADR-011): a path reaches it only
through a top-level rewrite placed before the frontend catch-all. Without one, QStash
delivers to the frontend, which answers 404, and a new store stays PROVISIONING forever. The same holds
for ``/webhooks/stripe``: without a rewrite Stripe never reaches the backend and a paid plan stays Free.
"""

import inspect
import json
import re
from pathlib import Path

import pytest

from app.services.store_provisioning_job import FAILED_PATH, STEP_PATH

VERCEL_JSON = Path(__file__).resolve().parents[3] / "vercel.json"
pytestmark = pytest.mark.skipif(
    not VERCEL_JSON.exists(), reason="root vercel.json is not in this checkout"
)
BACKEND_SERVICE = "fastapi_backend"
STRIPE_WEBHOOK_PATH = "/webhooks/stripe"
CONNECT_WEBHOOK_PATH = "/webhooks/stripe-connect"


def _rewrites() -> list[dict[str, object]]:
    return json.loads(VERCEL_JSON.read_text(encoding="utf-8"))["rewrites"]


def _destination_service(path: str) -> str | None:
    """The service of the first rewrite whose source matches ``path``."""
    for rule in _rewrites():
        source = str(rule["source"])
        if re.fullmatch(re.escape(source).replace(re.escape("(.*)"), ".*"), path):
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


@pytest.mark.parametrize(
    ("path", "service"),
    [
        (STRIPE_WEBHOOK_PATH, BACKEND_SERVICE),
        (CONNECT_WEBHOOK_PATH, BACKEND_SERVICE),
        ("/webhooks/stripe-connect/", "nextjs-frontend"),
        ("/webhooks/stripe/", "nextjs-frontend"),
        ("/webhooks/stripe/x", "nextjs-frontend"),
        ("/webhooks/stripe-other", "nextjs-frontend"),
        ("/webhooks", "nextjs-frontend"),
        ("/api/webhooks/stripe", "nextjs-frontend"),
    ],
)
def test_only_the_exact_stripe_path_reaches_the_backend(
    path: str, service: str
) -> None:
    assert _destination_service(path) == service


def test_only_the_intended_public_paths_reach_the_backend() -> None:
    backend_rules = [
        r for r in _rewrites() if r["destination"] == {"service": BACKEND_SERVICE}
    ]
    assert [r["source"] for r in backend_rules] == [
        "/internal/provisioning/(.*)",
        STRIPE_WEBHOOK_PATH,
        CONNECT_WEBHOOK_PATH,
    ]


async def test_the_connect_route_matches_the_rewrite_and_rejects_unsigned_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx import ASGITransport, AsyncClient
    from pydantic import SecretStr

    from app.api.deps import get_session_provider
    from app.api.v1.webhooks_connect import router
    from app.core.config import settings
    from app.main import create_app
    from tests.fakes import FakeSession, FakeSessionProvider

    monkeypatch.setattr(
        settings, "STRIPE_CONNECT_WEBHOOK_SECRET", SecretStr("whsec_routing_test_only")
    )
    assert {route.path for route in router.routes} == {CONNECT_WEBHOOK_PATH}  # type: ignore[attr-defined]
    app = create_app()
    app.dependency_overrides[get_session_provider] = lambda: FakeSessionProvider(
        FakeSession()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as http:
        unsigned = await http.post(CONNECT_WEBHOOK_PATH, content=b"{}")

    assert unsigned.status_code == 400
    assert unsigned.json() == {"success": False, "error": "Invalid signature"}


def test_the_stripe_route_matches_the_rewrite_and_checks_the_signature() -> None:
    from app.api.v1.webhooks import router

    assert {route.path for route in router.routes} == {STRIPE_WEBHOOK_PATH}  # type: ignore[attr-defined]
    for route in router.routes:
        assert "_verified_body(" in inspect.getsource(route.endpoint)  # type: ignore[attr-defined]


def test_the_rewrite_exposes_only_the_two_qstash_routes() -> None:
    from app.api.v1.internal_provisioning import router

    assert {route.path for route in router.routes} == {  # type: ignore[attr-defined]
        STEP_PATH,
        FAILED_PATH,
    }


def test_every_exposed_route_verifies_the_qstash_signature() -> None:
    from app.api.v1.internal_provisioning import router

    for route in router.routes:
        source = inspect.getsource(route.endpoint)  # type: ignore[attr-defined]
        assert "_verified_body(" in source, route.path
