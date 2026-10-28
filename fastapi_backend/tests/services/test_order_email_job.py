"""Order email jobs and their QStash publisher (KAN-81), without I/O."""

import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services import order_email_job
from app.services.order_email_job import (
    FAILED_PATH,
    ORDER_EMAIL_RETRIES,
    SEND_PATH,
    DisabledOrderEmailEnqueuer,
    EnqueueFailed,
    OrderEmailJob,
    QStashOrderEmailEnqueuer,
    build_order_email_enqueuer,
    is_valid_store_id,
    parse_job,
    publish_jobs,
    publish_quietly,
)
from app.services.order_email_templates import OrderEmailKind
from tests.fakes_email import RecordingEnqueuer

STORE_ID = "abcdefgh12345678abcdefgh"
ORDER_ID = "order1"
CONFIRM = OrderEmailJob(STORE_ID, ORDER_ID, OrderEmailKind.ORDER_CONFIRMATION)
SHIPPED = OrderEmailJob(STORE_ID, ORDER_ID, OrderEmailKind.ORDER_SHIPPED)
ALERT = OrderEmailJob(STORE_ID, ORDER_ID, OrderEmailKind.NEW_ORDER_ALERT)


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    events: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", events.append)
    return events


# --- payloads ---------------------------------------------------------------------------


def test_a_job_round_trips_through_its_payload() -> None:
    assert parse_job(json.loads(CONFIRM.payload())) == CONFIRM
    assert json.loads(CONFIRM.payload()) == {
        "store_id": STORE_ID,
        "order_id": ORDER_ID,
        "kind": "order_confirmation",
    }


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"store_id": STORE_ID, "order_id": ORDER_ID},
        {"store_id": STORE_ID, "order_id": ORDER_ID, "kind": "invoice"},
        {"store_id": STORE_ID, "order_id": "bad id", "kind": "order_shipped"},
        {"store_id": "Bad-Store!", "order_id": ORDER_ID, "kind": "order_shipped"},
        {"store_id": 1, "order_id": ORDER_ID, "kind": "order_shipped"},
        {
            "store_id": STORE_ID,
            "order_id": ORDER_ID,
            "kind": "order_shipped",
            "to": "x@y.test",
        },
    ],
)
def test_an_unusable_payload_is_refused(raw: Any) -> None:
    assert parse_job(raw) is None


def test_a_store_id_must_have_the_shape_of_a_real_one() -> None:
    assert is_valid_store_id(STORE_ID)
    assert not is_valid_store_id("Bad-Store!")


def test_ids_and_keys_name_the_store_order_and_kind() -> None:
    assert CONFIRM.dedup_id == f"order-email-{STORE_ID}-{ORDER_ID}-order_confirmation"
    assert CONFIRM.idempotency_key() == CONFIRM.dedup_id
    assert ALERT.idempotency_key("u1") == f"{ALERT.dedup_id}-u1"


# --- the QStash publisher ---------------------------------------------------------------


def qstash(handler: Any) -> QStashOrderEmailEnqueuer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return QStashOrderEmailEnqueuer(
        "qstash-token-placeholder",
        "https://qstash.upstash.io",
        "https://shop.example.com",
        client=client,
    )


async def test_qstash_publish_carries_ids_only_with_dedup_and_failure_callback() -> (
    None
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "m1"})

    await qstash(handler).enqueue(CONFIRM)

    [request] = seen
    assert str(request.url) == (
        f"https://qstash.upstash.io/v2/publish/https://shop.example.com{SEND_PATH}"
    )
    assert request.headers["Upstash-Deduplication-Id"] == CONFIRM.dedup_id
    assert request.headers["Upstash-Retries"] == str(ORDER_EMAIL_RETRIES)
    assert request.headers["Upstash-Failure-Callback"] == (
        f"https://shop.example.com{FAILED_PATH}"
    )
    assert json.loads(request.content) == json.loads(CONFIRM.payload())
    assert request.extensions["timeout"]["read"] == 3.0


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_publish_a_retry_can_fix_raises(
    status: int, caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    with pytest.raises(EnqueueFailed):
        await qstash(lambda request: httpx.Response(status)).enqueue(CONFIRM)

    assert "qstash-token-placeholder" not in caplog.text
    assert reported == []  # the 500 and Stripe's redelivery are the signal


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_a_publish_qstash_refuses_is_reported_and_never_raised(
    status: int, caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    await qstash(lambda request: httpx.Response(status)).enqueue(CONFIRM)

    assert [str(error) for error in reported] == [
        f"qstash refused the publish: {status}"
    ]
    record = next(r for r in caplog.records if "refused" in r.getMessage())
    assert record.levelno == logging.ERROR
    assert record.order_id == ORDER_ID
    assert "qstash-token-placeholder" not in caplog.text


async def test_a_publish_network_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(EnqueueFailed):
        await qstash(handler).enqueue(CONFIRM)


async def test_qstash_publish_without_an_injected_client(monkeypatch) -> None:
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda: real(transport=httpx.MockTransport(handler))
    )

    await QStashOrderEmailEnqueuer(
        "t", "https://qstash.upstash.io", "https://s"
    ).enqueue(CONFIRM)

    assert len(seen) == 1


def settings_with(**values: object) -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
        ENVIRONMENT="test",
        **values,  # type: ignore[arg-type]
    )


def test_qstash_is_used_when_configured() -> None:
    configured = settings_with(
        QSTASH_TOKEN=SecretStr("t"), PROVISIONING_BASE_URL="https://shop.example.com"
    )

    assert isinstance(build_order_email_enqueuer(configured), QStashOrderEmailEnqueuer)
    assert isinstance(
        build_order_email_enqueuer(settings_with()), DisabledOrderEmailEnqueuer
    )


async def test_without_qstash_nothing_is_published_and_ids_are_logged(
    caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    await DisabledOrderEmailEnqueuer().enqueue(CONFIRM)

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.order_id == ORDER_ID
    assert record.kind == "order_confirmation"
    assert reported == []


async def test_without_qstash_outside_local_it_is_an_error_and_a_sentry_event(
    caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    await DisabledOrderEmailEnqueuer(relaxed=False).enqueue(CONFIRM)

    assert [record.levelno for record in caplog.records] == [logging.ERROR]
    assert [str(error) for error in reported] == ["qstash not configured"]


async def test_publish_jobs_reraises_an_unexpected_crash() -> None:
    class Crashing:
        async def enqueue(self, job: OrderEmailJob) -> None:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await publish_jobs(Crashing(), [CONFIRM])


async def test_publish_jobs_tries_every_job_then_raises() -> None:
    class FirstFails(RecordingEnqueuer):
        async def enqueue(self, job: OrderEmailJob) -> None:
            if not self.jobs and not self.fail:
                self.fail = True
                raise EnqueueFailed
            self.jobs.append(job)

    enqueuer = FirstFails()

    with pytest.raises(EnqueueFailed):
        await publish_jobs(enqueuer, [CONFIRM, ALERT])

    assert enqueuer.jobs == [ALERT]


async def test_publish_quietly_logs_and_reports(
    caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)

    await publish_quietly(RecordingEnqueuer(fail=True), [SHIPPED])

    assert [str(error) for error in reported] == ["order_shipped: EnqueueFailed"]
    record = next(r for r in caplog.records if "publish" in r.getMessage())
    assert record.order_id == ORDER_ID


async def test_publish_quietly_reports_an_unexpected_crash(
    reported: list[BaseException],
) -> None:
    class Crashing:
        async def enqueue(self, job: OrderEmailJob) -> None:
            raise RuntimeError("boom")

    await publish_quietly(Crashing(), [SHIPPED])

    assert [str(error) for error in reported] == ["order_shipped: RuntimeError"]
