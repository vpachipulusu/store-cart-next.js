"""Provisioning job without a database (KAN-56): enqueuing, payloads, settings."""

import json
import logging

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.services import store_provisioning_job
from app.services.store_provisioning_job import (
    EnqueueFailed,
    NoopEnqueuer,
    QStashEnqueuer,
    Step,
    UnconfiguredEnqueuer,
    get_step_enqueuer,
    parse_step_payload,
    start_provisioning,
)

TOKEN = "qstash-secret-token-123"
STORE_ID = "abcdefgh12345678abcdefgh"
CALLBACK = "https://api.example.test"


def enqueuer_with(handler, retries: int = 5) -> QStashEnqueuer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return QStashEnqueuer(
        TOKEN,
        "https://qstash.upstash.io",
        CALLBACK,
        retries=retries,
        client=client,
    )


async def test_publishes_the_step_with_retries_and_a_failure_callback():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "m"})

    await enqueuer_with(handler, retries=3).enqueue(
        STORE_ID, Step.RUN_MIGRATIONS, attempt=0
    )

    request = seen[0]
    assert request.method == "POST"
    assert request.url.host == "qstash.upstash.io"
    assert request.url.path == f"/v2/publish/{CALLBACK}/internal/provisioning/step"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["upstash-retries"] == "3"
    assert (
        request.headers["upstash-failure-callback"]
        == f"{CALLBACK}/internal/provisioning/failed"
    )
    assert (
        request.headers["upstash-deduplication-id"]
        == f"provision-{STORE_ID}-run_migrations-a0"
    )
    assert json.loads(request.content) == {
        "store_id": STORE_ID,
        "step": "run_migrations",
        "attempt": 0,
    }


async def test_admin_rerun_gets_its_own_deduplication_id():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "m"})

    enqueuer = enqueuer_with(handler)
    await enqueuer.enqueue(STORE_ID, Step.CREATE_DATABASE, attempt=2)

    assert (
        seen[0].headers["upstash-deduplication-id"]
        == f"provision-{STORE_ID}-create_database-a2"
    )


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_raises_enqueue_failed_when_qstash_rejects(status, caplog):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(EnqueueFailed):
        await enqueuer_with(lambda r: httpx.Response(status)).enqueue(
            STORE_ID, Step.CREATE_DATABASE, attempt=0
        )

    assert TOKEN not in caplog.text


async def test_raises_enqueue_failed_on_a_network_error_without_leaking(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} {TOKEN}")

    caplog.set_level(logging.DEBUG)

    with pytest.raises(EnqueueFailed) as raised:
        await enqueuer_with(handler).enqueue(STORE_ID, Step.CREATE_DATABASE, attempt=0)

    assert raised.value.__cause__ is None
    assert TOKEN not in caplog.text
    assert "ConnectError" in caplog.text


class RecordingEnqueuer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, Step]] = []

    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        self.calls.append((store_id, step))
        if self.fail:
            raise EnqueueFailed


async def test_start_provisioning_enqueues_create_database_first():
    enqueuer = RecordingEnqueuer()

    started = await start_provisioning(object(), enqueuer, STORE_ID)  # type: ignore[arg-type]

    assert started is True
    assert enqueuer.calls == [(STORE_ID, Step.CREATE_DATABASE)]


async def test_start_provisioning_marks_the_store_failed_when_enqueue_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    marked: list[str] = []

    async def fake_mark_failed(provider, store_id: str) -> bool:
        marked.append(store_id)
        return True

    monkeypatch.setattr(store_provisioning_job, "mark_failed", fake_mark_failed)

    started = await start_provisioning(
        object(),  # type: ignore[arg-type]
        RecordingEnqueuer(fail=True),
        STORE_ID,
    )

    assert started is False
    assert marked == [STORE_ID]


def settings_with(**values: object) -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
        ENVIRONMENT="test",
        **values,  # type: ignore[arg-type]
    )


def test_enqueuer_is_qstash_when_token_and_callback_url_are_set():
    settings = settings_with(QSTASH_TOKEN=TOKEN, PROVISIONING_BASE_URL=CALLBACK)

    assert isinstance(get_step_enqueuer(settings), QStashEnqueuer)


def test_enqueuer_is_a_noop_in_local_and_test_without_qstash():
    assert isinstance(get_step_enqueuer(settings_with()), NoopEnqueuer)


async def test_unconfigured_enqueuer_refuses_to_enqueue():
    with pytest.raises(EnqueueFailed):
        await UnconfiguredEnqueuer().enqueue(STORE_ID, Step.CREATE_DATABASE, attempt=0)


def test_signing_keys_list_current_then_next_and_skip_unset():
    both = settings_with(
        QSTASH_CURRENT_SIGNING_KEY="cur", QSTASH_NEXT_SIGNING_KEY="nxt"
    )
    one = settings_with(QSTASH_NEXT_SIGNING_KEY="nxt")

    assert both.qstash_signing_keys == ["cur", "nxt"]
    assert one.qstash_signing_keys == ["nxt"]
    assert settings_with().qstash_signing_keys == []


@pytest.mark.parametrize(
    "url",
    [
        "http://qstash.upstash.io",
        "https://evil.example.com",
        "https://upstash.io.evil.com",
    ],
)
def test_rejects_a_qstash_url_that_is_not_https_on_upstash(url):
    with pytest.raises(ValidationError):
        settings_with(QSTASH_URL=url)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://api.example.test",
        "http://api.example.test",
        "https://user:pw@api.example.test",
        "https://api.example.test/?x=1",
    ],
)
def test_rejects_an_unsafe_provisioning_base_url(url):
    with pytest.raises(ValidationError):
        settings_with(PROVISIONING_BASE_URL=url)


def test_allows_http_localhost_as_the_provisioning_base_url_in_test():
    settings = settings_with(PROVISIONING_BASE_URL="http://localhost:8000")

    assert settings.PROVISIONING_BASE_URL == "http://localhost:8000"


def test_secrets_are_not_shown_in_the_settings_repr():
    settings = settings_with(QSTASH_TOKEN=TOKEN, QSTASH_CURRENT_SIGNING_KEY="sig-key")

    assert TOKEN not in repr(settings)
    assert "sig-key" not in repr(settings)
    assert isinstance(settings.QSTASH_TOKEN, SecretStr)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"store_id": STORE_ID, "step": "create_database"},
            (Step.CREATE_DATABASE, STORE_ID, 0),
        ),
        (
            {"store_id": STORE_ID, "step": "mark_ready", "attempt": 3},
            (Step.MARK_READY, STORE_ID, 3),
        ),
        ({"store_id": STORE_ID, "step": "mark_ready", "attempt": -1}, None),
        ({"store_id": STORE_ID, "step": "mark_ready", "attempt": True}, None),
        ({"store_id": STORE_ID, "step": "mark_ready", "attempt": "1"}, None),
        ({"store_id": STORE_ID, "step": "mark_ready", "attempt": 10**6}, None),
        ({"store_id": STORE_ID, "step": "bogus"}, None),
        ({"store_id": "UPPER", "step": "mark_ready"}, None),
        ({"store_id": STORE_ID}, None),
        ({"store_id": 5, "step": "mark_ready"}, None),
        ({"store_id": STORE_ID, "step": "mark_ready", "extra": 1}, None),
        ([], None),
        (None, None),
    ],
)
def test_parse_step_payload(raw, expected):
    assert parse_step_payload(raw) == expected


class CrashingEnqueuer:
    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        raise UnicodeError("unexpected")


async def test_start_provisioning_marks_failed_when_the_enqueuer_crashes(
    monkeypatch: pytest.MonkeyPatch,
):
    marked: list[str] = []

    async def fake_mark_failed(provider, store_id: str) -> bool:
        marked.append(store_id)
        return True

    monkeypatch.setattr(store_provisioning_job, "mark_failed", fake_mark_failed)

    started = await start_provisioning(object(), CrashingEnqueuer(), STORE_ID)  # type: ignore[arg-type]

    assert started is False
    assert marked == [STORE_ID]


def production_settings(**values: object) -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
        ENVIRONMENT="production",
        BACKEND_INTERNAL_KEY="k" * 32,
        RATE_LIMIT_EMAIL_KEY="k" * 32,
        FIREBASE_ADMIN_PROJECT_ID="p",
        FIREBASE_ADMIN_CLIENT_EMAIL="e@example.test",
        FIREBASE_ADMIN_PRIVATE_KEY="x",
        UPSTASH_REDIS_REST_URL="https://redis.example.test",
        UPSTASH_REDIS_REST_TOKEN="t",
        STORE_DB_ENCRYPTION_KEY="A" * 43,
        **values,  # type: ignore[arg-type]
    )


def test_production_accepts_qstash_fully_configured_or_not_at_all():
    production_settings()
    production_settings(
        QSTASH_TOKEN=TOKEN,
        PROVISIONING_BASE_URL=CALLBACK,
        QSTASH_CURRENT_SIGNING_KEY="cur",
    )


@pytest.mark.parametrize(
    "values",
    [
        {"QSTASH_TOKEN": TOKEN},
        {"QSTASH_TOKEN": TOKEN, "PROVISIONING_BASE_URL": CALLBACK},
        {"PROVISIONING_BASE_URL": CALLBACK, "QSTASH_CURRENT_SIGNING_KEY": "cur"},
    ],
)
def test_production_rejects_a_half_configured_qstash(values):
    with pytest.raises(ValidationError):
        production_settings(**values)


def test_accepts_regional_qstash_hosts():
    settings = settings_with(QSTASH_URL="https://qstash-us-east-1.upstash.io")

    assert settings.QSTASH_URL.endswith("qstash-us-east-1.upstash.io")


def test_rejects_other_upstash_hosts():
    with pytest.raises(ValidationError):
        settings_with(QSTASH_URL="https://my-redis.upstash.io")
