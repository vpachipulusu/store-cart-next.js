"""QStash callback that purges expired carts (KAN-252): signature, configuration, result.

Built from ``create_app()`` so the real mounting, error envelope and OpenAPI exclusion are
exercised. The purge itself is replaced; its behaviour is covered in the service tests.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from app.api.v1.internal_cart_purge import get_cart_purger
from app.core.config import settings
from app.main import create_app
from app.services.store_cart_purge import PURGE_PATH, PurgeSummary
from tests.qstash_tokens import make_token

BASE = "https://api.example.test"
KEY = "current-signing-key-for-tests"
NEXT_KEY = "next-signing-key-for-tests"


class Recorder:
    def __init__(self) -> None:
        self.runs = 0
        self.error: Exception | None = None
        self.summary = PurgeSummary(stores=2, carts_deleted=7, stores_failed=1)

    async def __call__(self) -> PurgeSummary:
        self.runs += 1
        if self.error is not None:
            raise self.error
        return self.summary


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROVISIONING_BASE_URL", BASE)
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "QSTASH_NEXT_SIGNING_KEY", SecretStr(NEXT_KEY))


@pytest.fixture
def purger() -> Recorder:
    return Recorder()


@pytest.fixture
async def client(purger: Recorder) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_cart_purger] = lambda: purger
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        yield http


def signed(body: bytes = b"", key: str = KEY, path: str = PURGE_PATH) -> dict[str, str]:
    return {"Upstash-Signature": make_token(body, f"{BASE}{path}", key)}


async def test_a_signed_schedule_call_runs_the_purge_and_reports_counts(
    client: httpx.AsyncClient, purger: Recorder
) -> None:
    response = await client.post(PURGE_PATH, headers=signed())

    assert response.status_code == 200
    assert response.json() == {"stores": 2, "carts_deleted": 7, "stores_failed": 1}
    assert purger.runs == 1


async def test_the_next_signing_key_is_accepted_during_rotation(
    client: httpx.AsyncClient, purger: Recorder
) -> None:
    response = await client.post(PURGE_PATH, headers=signed(key=NEXT_KEY))

    assert response.status_code == 200
    assert purger.runs == 1


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Upstash-Signature": "not-a-jwt"},
        signed(key="wrong-key"),
        signed(path="/internal/provisioning/step"),
        signed(body=b"tampered"),
    ],
    ids=["missing", "garbage", "wrong-key", "other-url", "other-body"],
)
async def test_an_unsigned_or_misdirected_call_is_401_and_purges_nothing(
    client: httpx.AsyncClient, purger: Recorder, headers: dict[str, str]
) -> None:
    response = await client.post(PURGE_PATH, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"success": False, "error": "Invalid signature"}
    assert purger.runs == 0


async def test_unconfigured_signing_is_503_and_purges_nothing(
    client: httpx.AsyncClient, purger: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PROVISIONING_BASE_URL", None)

    response = await client.post(PURGE_PATH, headers=signed())

    assert response.status_code == 503
    assert purger.runs == 0


async def test_an_oversized_body_is_refused_and_purges_nothing(
    client: httpx.AsyncClient, purger: Recorder
) -> None:
    response = await client.post(PURGE_PATH, content=b"x" * 70_000, headers=signed())

    assert response.status_code == 413
    assert purger.runs == 0


async def test_a_failing_purge_is_500_so_qstash_retries(
    client: httpx.AsyncClient, purger: Recorder
) -> None:
    purger.error = RuntimeError("platform database down")

    response = await client.post(PURGE_PATH, headers=signed())

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "Internal server error"}


async def test_the_route_is_not_in_the_openapi_schema(
    client: httpx.AsyncClient,
) -> None:
    schema = (await client.get("/openapi.json")).text

    assert PURGE_PATH not in schema


async def test_a_run_where_every_store_failed_is_500_so_qstash_retries(
    client: httpx.AsyncClient, purger: Recorder
) -> None:
    purger.summary = PurgeSummary(stores=3, carts_deleted=0, stores_failed=3)

    response = await client.post(PURGE_PATH, headers=signed())

    assert response.status_code == 500


async def test_a_run_with_no_stores_is_200(
    client: httpx.AsyncClient, purger: Recorder
) -> None:
    purger.summary = PurgeSummary(stores=0, carts_deleted=0, stores_failed=0)

    response = await client.post(PURGE_PATH, headers=signed())

    assert response.status_code == 200
