"""QStash callback routes of the provisioning job (KAN-56): signature, payload, retry."""

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.api.deps import get_session_provider
from app.api.v1 import internal_provisioning
from app.api.v1.internal_provisioning import get_step_runner
from app.core.config import settings
from app.services.store_provisioning_job import FAILED_PATH, STEP_PATH, Step, StepFailed
from tests.qstash_tokens import make_token

BASE = "https://api.example.test"
KEY = "current-signing-key-for-tests"
NEXT_KEY = "next-signing-key-for-tests"
STORE_ID = "abcdefgh12345678abcdefgh"


class RecordingRunner:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[Step, str]] = []
        self.error = error

    async def run(self, step: Step, store_id: str) -> None:
        self.calls.append((step, store_id))
        if self.error:
            raise self.error


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROVISIONING_BASE_URL", BASE)
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "QSTASH_NEXT_SIGNING_KEY", SecretStr(NEXT_KEY))


@pytest.fixture
def runner() -> RecordingRunner:
    return RecordingRunner()


@pytest.fixture
def failed_marks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    marked: list[str] = []

    async def fake_mark_failed(provider: Any, store_id: str) -> bool:
        marked.append(store_id)
        return True

    monkeypatch.setattr(internal_provisioning, "mark_failed", fake_mark_failed)
    return marked


@pytest.fixture
async def client(runner: RecordingRunner) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(internal_provisioning.router)
    app.dependency_overrides[get_step_runner] = lambda: runner
    app.dependency_overrides[get_session_provider] = lambda: object()
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


async def test_answers_503_when_signing_keys_are_not_configured(
    client, runner, monkeypatch
):
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", None)
    monkeypatch.setattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)

    response = await post(client, STEP_PATH, step_body())

    assert response.status_code == 503
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
async def test_rejects_an_invalid_payload_after_the_signature_check(
    client, runner, body
):
    response = await post(client, STEP_PATH, body)

    assert response.status_code == 400
    assert runner.calls == []


async def test_rejects_an_oversized_body(client, runner):
    body = b"x" * (internal_provisioning.MAX_BODY_BYTES + 1)

    response = await post(client, STEP_PATH, body)

    assert response.status_code == 413
    assert runner.calls == []


async def test_answers_500_without_details_so_qstash_retries(client, runner):
    runner.error = StepFailed()

    response = await post(client, STEP_PATH, step_body())

    assert response.status_code == 500
    assert response.json() == {"detail": "Provisioning step failed"}


async def test_failure_callback_marks_the_store_failed(client, failed_marks):
    response = await post(client, FAILED_PATH, callback_body(step_body()))

    assert response.status_code == 200
    assert failed_marks == [STORE_ID]


async def test_failure_callback_requires_a_signature(client, failed_marks):
    response = await client.post(FAILED_PATH, content=callback_body(step_body()))

    assert response.status_code == 401
    assert failed_marks == []


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"sourceBody": "***"}',
        json.dumps({"sourceBody": base64.b64encode(b"nope").decode()}).encode(),
        callback_body(b'{"store_id": "x", "step": "mark_ready"}'),
    ],
)
async def test_failure_callback_rejects_an_invalid_payload(client, failed_marks, body):
    response = await post(client, FAILED_PATH, body)

    assert response.status_code == 400
    assert failed_marks == []
