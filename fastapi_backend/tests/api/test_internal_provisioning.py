"""QStash callback routes of the provisioning job (KAN-56): signature, payload, retry.

Built from ``create_app()`` so the real mounting, error envelope and OpenAPI exclusion
are exercised. The runner is replaced; its own behaviour is covered in the service tests.
"""

import base64
import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from pydantic import SecretStr

from app.api.v1 import internal_provisioning
from app.api.v1.internal_provisioning import get_step_runner
from app.core.config import settings
from app.main import create_app
from app.services.store_provisioning_job import (
    FAILED_PATH,
    STEP_PATH,
    Step,
    StepFailed,
    StepRunner,
)
from tests.qstash_tokens import make_token

BASE = "https://api.example.test"
KEY = "current-signing-key-for-tests"
NEXT_KEY = "next-signing-key-for-tests"
STORE_ID = "abcdefgh12345678abcdefgh"
NON_RETRYABLE = "Upstash-NonRetryable-Error"


class RecordingRunner(StepRunner):
    """Real payload handling; the step itself and the FAILED write are recorded."""

    def __init__(self) -> None:
        super().__init__(provider=None, provisioner=None, enqueuer=None)  # type: ignore[arg-type]
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "failed", [])
        object.__setattr__(self, "error", None)

    async def run(self, step: Step, store_id: str) -> None:
        self.calls.append((step, store_id))  # type: ignore[attr-defined]
        if self.error:  # type: ignore[attr-defined]
            raise self.error  # type: ignore[attr-defined]

    async def fail(self, store_id: str) -> None:
        self.failed.append(store_id)  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROVISIONING_BASE_URL", BASE)
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "QSTASH_NEXT_SIGNING_KEY", SecretStr(NEXT_KEY))


@pytest.fixture
def runner() -> RecordingRunner:
    return RecordingRunner()


@pytest.fixture
async def client(runner: RecordingRunner) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_step_runner] = lambda: runner
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        yield http


def step_body(step: str = "create_database", store_id: str = STORE_ID) -> bytes:
    return json.dumps({"store_id": store_id, "step": step}).encode()


def callback_body(source: bytes) -> bytes:
    return json.dumps(
        {"status": 500, "sourceBody": base64.b64encode(source).decode()}
    ).encode()


async def post(
    client: httpx.AsyncClient,
    path: str,
    body: bytes,
    *,
    token: str | None = None,
    key: str = KEY,
    signed_path: str | None = None,
) -> httpx.Response:
    signature = token or make_token(body, f"{BASE}{signed_path or path}", key)
    return await client.post(
        path,
        content=body,
        headers={"Content-Type": "application/json", "Upstash-Signature": signature},
    )


def error_of(response: httpx.Response) -> str:
    body = response.json()
    assert body["success"] is False
    return str(body["error"])


async def test_routes_are_mounted_and_hidden_from_the_openapi_schema(client):
    schema = (await client.get("/openapi.json")).json()

    assert not [path for path in schema["paths"] if path.startswith("/internal")]
    # Mounted: an unsigned call reaches the signature check, it is not a 404.
    assert (await client.post(STEP_PATH, content=b"{}")).status_code == 401


async def test_runs_the_step_for_a_signed_delivery(client, runner):
    response = await post(client, STEP_PATH, step_body("run_migrations"))

    assert response.status_code == 200
    assert runner.calls == [(Step.RUN_MIGRATIONS, STORE_ID)]


async def test_accepts_a_delivery_signed_with_the_next_key(client, runner):
    response = await post(client, STEP_PATH, step_body(), key=NEXT_KEY)

    assert response.status_code == 200
    assert len(runner.calls) == 1


async def test_rejects_an_unsigned_delivery(client, runner):
    response = await client.post(STEP_PATH, content=step_body())

    assert response.status_code == 401
    assert error_of(response) == "Invalid signature"
    assert runner.calls == []


async def test_rejects_a_delivery_signed_with_another_key(client, runner):
    response = await post(client, STEP_PATH, step_body(), key="not-the-key")

    assert response.status_code == 401
    assert runner.calls == []


async def test_rejects_a_token_signed_for_the_other_route(client, runner):
    response = await post(client, STEP_PATH, step_body(), signed_path=FAILED_PATH)

    assert response.status_code == 401
    assert runner.calls == []


async def test_rejects_a_tampered_body(client, runner):
    token = make_token(step_body(), f"{BASE}{STEP_PATH}", KEY)

    response = await post(
        client, STEP_PATH, step_body(store_id="zzzzzzzz12345678zzzzzzzz"), token=token
    )

    assert response.status_code == 401
    assert runner.calls == []


async def test_answers_503_and_stays_retryable_when_keys_are_not_configured(
    client, runner, monkeypatch
):
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", None)
    monkeypatch.setattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)

    response = await post(client, STEP_PATH, step_body())

    assert response.status_code == 503
    assert NON_RETRYABLE not in response.headers
    assert runner.calls == []


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"store_id": "abcdefgh12345678abcdefgh"}',
        b'{"store_id": "abcdefgh12345678abcdefgh", "step": "drop_everything"}',
        b'{"store_id": "../etc", "step": "create_database"}',
        b'{"store_id": "abcdefgh12345678abcdefgh", "step": "mark_ready", "x": 1}',
    ],
)
async def test_a_signed_but_invalid_payload_is_400_and_not_retried(
    client, runner, body
):
    response = await post(client, STEP_PATH, body)

    assert response.status_code == 400
    assert response.headers[NON_RETRYABLE] == "true"
    assert error_of(response) == "Invalid payload"
    assert runner.calls == []


async def test_an_oversized_body_is_413_and_not_retried(client, runner):
    body = b"x" * (internal_provisioning.MAX_BODY_BYTES + 1)

    response = await post(client, STEP_PATH, body)

    assert response.status_code == 413
    assert response.headers[NON_RETRYABLE] == "true"
    assert runner.calls == []


async def test_answers_500_without_details_so_qstash_retries(client, runner):
    runner.error = StepFailed()

    response = await post(client, STEP_PATH, step_body())

    assert response.status_code == 500
    assert NON_RETRYABLE not in response.headers
    assert error_of(response) == "Provisioning step failed"


async def test_failure_callback_marks_the_store_failed(client, runner):
    response = await post(client, FAILED_PATH, callback_body(step_body()))

    assert response.status_code == 200
    assert runner.failed == [STORE_ID]


async def test_failure_callback_requires_a_signature(client, runner):
    response = await client.post(FAILED_PATH, content=callback_body(step_body()))

    assert response.status_code == 401
    assert runner.failed == []


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"sourceBody": "***"}',
        json.dumps({"sourceBody": base64.b64encode(b"nope").decode()}).encode(),
        callback_body(b'{"store_id": "x", "step": "mark_ready"}'),
    ],
)
async def test_failure_callback_rejects_an_invalid_payload_without_retry(
    client, runner, body
):
    response = await post(client, FAILED_PATH, body)

    assert response.status_code == 400
    assert response.headers[NON_RETRYABLE] == "true"
    assert runner.failed == []


@pytest.fixture(autouse=True)
def _reset_overrides() -> Iterator[None]:
    yield
