"""The order email job (KAN-81): payloads, the QStash publisher and the runner, without I/O."""

import base64
import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.repositories.order_email_context import AlertRecipient, StoreEmailContext
from app.services import order_email_job
from app.services.email import (
    EmailDeliveryFailed,
    EmailDisabled,
    EmailMessage,
    EmailRejected,
)
from app.services.order_email_job import (
    FAILED_PATH,
    ORDER_EMAIL_RETRIES,
    SEND_PATH,
    DisabledOrderEmailEnqueuer,
    EmailStatus,
    EnqueueFailed,
    InvalidPayload,
    OrderEmailJob,
    OrderEmailRunner,
    PendingEmail,
    QStashOrderEmailEnqueuer,
    SendFailed,
    clean_customer_email,
    get_order_email_enqueuer,
    parse_job,
    publish_jobs,
    publish_quietly,
)
from app.services.order_email_templates import (
    OrderEmailKind,
    OrderFacts,
    OrderLine,
    TemplateText,
)
from tests.fakes_email import (
    FakeDirectory,
    FakeOutbox,
    RecordingEnqueuer,
    RecordingSender,
)

STORE_ID = "abcdefgh12345678abcdefgh"
ORDER_ID = "order1"
CUSTOMER = "shopper@example.com"
APP_URL = "https://app.example.com"
FACTS = OrderFacts(
    ORDER_ID, "GBP", 2000, (OrderLine("Mug", None, 2, 1000),), "TRK1", None
)
CONFIRM = OrderEmailJob(STORE_ID, ORDER_ID, OrderEmailKind.ORDER_CONFIRMATION)
SHIPPED = OrderEmailJob(STORE_ID, ORDER_ID, OrderEmailKind.ORDER_SHIPPED)
ALERT = OrderEmailJob(STORE_ID, ORDER_ID, OrderEmailKind.NEW_ORDER_ALERT)
STORE = StoreEmailContext("North Shop", "orgA")
OWNERS = [
    AlertRecipient("u1", "owner@example.com"),
    AlertRecipient("u2", "admin@x.test"),
]


def body(job: OrderEmailJob) -> bytes:
    return json.dumps(
        {"store_id": job.store_id, "order_id": job.order_id, "kind": job.kind.value}
    ).encode()


def runner(
    *jobs: OrderEmailJob,
    customer: str | None = CUSTOMER,
    override: TemplateText | None = None,
    sender: RecordingSender | None = None,
    directory: FakeDirectory | None = None,
) -> tuple[OrderEmailRunner, FakeOutbox, RecordingSender]:
    outbox = FakeOutbox({job: PendingEmail(FACTS, customer, override) for job in jobs})
    sender = sender or RecordingSender()
    built = OrderEmailRunner(
        outbox=outbox,
        directory=directory or FakeDirectory(STORE, OWNERS),
        sender=sender,
        app_url=APP_URL,
    )
    return built, outbox, sender


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


def test_ids_and_keys_name_the_store_order_and_kind() -> None:
    assert CONFIRM.dedup_id == f"order-email-{STORE_ID}-{ORDER_ID}-order_confirmation"
    assert CONFIRM.idempotency_key() == CONFIRM.dedup_id
    assert ALERT.idempotency_key("u1") == f"{ALERT.dedup_id}-u1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Shopper@Example.com ", "Shopper@Example.com"),
        ("a@b", "a@b"),
        ("@example.com", None),
        ("no-at-sign", None),
        ("a b@example.com", None),
        ("a\n@example.com", None),
        ("x" * 250 + "@a.co", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_the_customer_email_is_trimmed_and_checked(raw: object, expected: str | None):
    assert clean_customer_email(raw) == expected


# --- publishing -------------------------------------------------------------------------


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


@pytest.mark.parametrize("status", [400, 500])
async def test_a_rejected_publish_raises(status: int, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(EnqueueFailed):
        await qstash(lambda request: httpx.Response(status)).enqueue(CONFIRM)

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

    assert isinstance(get_order_email_enqueuer(configured), QStashOrderEmailEnqueuer)
    assert isinstance(
        get_order_email_enqueuer(settings_with()), DisabledOrderEmailEnqueuer
    )


async def test_without_qstash_nothing_is_published_and_ids_are_logged(caplog) -> None:
    caplog.set_level(logging.DEBUG)

    await DisabledOrderEmailEnqueuer().enqueue(CONFIRM)

    [record] = caplog.records
    assert record.order_id == ORDER_ID
    assert record.kind == "order_confirmation"


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


async def test_publish_quietly_logs_and_reports(monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)

    await publish_quietly(RecordingEnqueuer(fail=True), [SHIPPED])

    assert [str(error) for error in reported] == ["order_shipped: EnqueueFailed"]
    record = next(r for r in caplog.records if "publish" in r.getMessage())
    assert record.order_id == ORDER_ID


async def test_publish_quietly_reports_an_unexpected_crash(monkeypatch) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)

    class Crashing:
        async def enqueue(self, job: OrderEmailJob) -> None:
            raise RuntimeError("boom")

    await publish_quietly(Crashing(), [SHIPPED])

    assert [str(error) for error in reported] == ["order_shipped: RuntimeError"]


# --- the runner -------------------------------------------------------------------------


async def test_the_confirmation_goes_to_the_shopper_and_is_marked_sent() -> None:
    built, outbox, sender = runner(CONFIRM)

    status = await built.handle_send(body(CONFIRM))

    assert status is EmailStatus.SENT
    [message] = sender.sent
    assert message.to == CUSTOMER
    assert message.kind == "order_confirmation"
    assert message.idempotency_key == CONFIRM.dedup_id
    assert "North Shop" in message.subject
    assert outbox.finished == [(CONFIRM, EmailStatus.SENT)]


async def test_the_shipped_notice_uses_the_store_override() -> None:
    built, _, sender = runner(
        SHIPPED, override=TemplateText("Shipped: $tracking_number", "Body")
    )

    await built.handle_send(body(SHIPPED))

    assert sender.sent[0].subject == "Shipped: TRK1"


async def test_the_alert_goes_to_each_recipient_with_its_own_key() -> None:
    built, outbox, sender = runner(ALERT)

    await built.handle_send(body(ALERT))

    assert [(m.to, m.idempotency_key) for m in sender.sent] == [
        ("owner@example.com", f"{ALERT.dedup_id}-u1"),
        ("admin@x.test", f"{ALERT.dedup_id}-u2"),
    ]
    assert f"{APP_URL}/dashboard/orders/{ORDER_ID}" in sender.sent[0].html
    assert outbox.finished == [(ALERT, EmailStatus.SENT)]


async def test_a_row_that_is_not_pending_sends_nothing() -> None:
    built, outbox, sender = runner()

    status = await built.handle_send(body(CONFIRM))

    assert status is None
    assert sender.sent == []
    assert outbox.finished == []


@pytest.mark.parametrize(
    ("job", "customer", "directory"),
    [
        (CONFIRM, None, None),
        (SHIPPED, None, None),
        (ALERT, CUSTOMER, FakeDirectory(STORE, [])),
    ],
)
async def test_no_recipient_is_skipped(
    job: OrderEmailJob, customer: str | None, directory: FakeDirectory | None
) -> None:
    built, outbox, sender = runner(job, customer=customer, directory=directory)

    status = await built.handle_send(body(job))

    assert status is EmailStatus.SKIPPED
    assert sender.sent == []
    assert outbox.finished == [(job, EmailStatus.SKIPPED)]


async def test_a_job_of_a_store_that_is_gone_ends_without_opening_its_database() -> (
    None
):
    built, outbox, sender = runner(CONFIRM, directory=FakeDirectory(None, OWNERS))
    outbox.load_error = AssertionError("the store database must not be opened")

    status = await built.handle_send(body(CONFIRM))
    await built.handle_exhausted(callback(body(CONFIRM)))

    assert status is None
    assert sender.sent == []
    assert outbox.finished == []


async def test_disabled_email_is_skipped() -> None:
    sender = RecordingSender({CUSTOMER: EmailDisabled()})
    built, outbox, _ = runner(CONFIRM, sender=sender)

    status = await built.handle_send(body(CONFIRM))

    assert status is EmailStatus.SKIPPED
    assert outbox.finished == [(CONFIRM, EmailStatus.SKIPPED)]


async def test_a_rejected_message_fails_for_good_and_is_reported(monkeypatch) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)
    sender = RecordingSender({CUSTOMER: EmailRejected()})
    built, outbox, _ = runner(CONFIRM, sender=sender)

    status = await built.handle_send(body(CONFIRM))

    assert status is EmailStatus.FAILED
    assert outbox.finished == [(CONFIRM, EmailStatus.FAILED)]
    assert [str(error) for error in reported] == ["order_confirmation: rejected"]


@pytest.mark.parametrize("error", [EmailDeliveryFailed(), TimeoutError()])
async def test_a_transient_failure_counts_an_attempt_and_asks_for_a_retry(
    error: BaseException,
) -> None:
    sender = RecordingSender({CUSTOMER: error})
    built, outbox, _ = runner(CONFIRM, sender=sender)

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert outbox.attempts == [CONFIRM]
    assert outbox.finished == []
    assert CONFIRM in outbox.pending


async def test_a_slow_provider_times_out(monkeypatch) -> None:
    monkeypatch.setattr(order_email_job, "SEND_TIMEOUT_SECONDS", 0.01)

    class Slow(RecordingSender):
        async def send(self, message: EmailMessage) -> None:
            import asyncio

            await asyncio.sleep(1)

    built, outbox, _ = runner(CONFIRM, sender=Slow())

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert outbox.attempts == [CONFIRM]


async def test_one_failing_alert_recipient_retries_the_whole_alert() -> None:
    sender = RecordingSender({"owner@example.com": EmailDeliveryFailed()})
    built, outbox, _ = runner(ALERT, sender=sender)

    with pytest.raises(SendFailed):
        await built.handle_send(body(ALERT))

    assert (
        len(sender.sent) == 2
    )  # the other recipient still got it; its key dedupes a retry
    assert outbox.attempts == [ALERT]


async def test_a_store_read_failure_asks_for_a_retry_and_reports(monkeypatch):
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)
    built, outbox, _ = runner(CONFIRM)
    outbox.load_error = RuntimeError("postgresql://user:secret@host/db")

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert ["secret" in str(error) for error in reported] == [False]


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"store_id": 1}'])
async def test_a_bad_delivery_is_an_invalid_payload(raw: bytes) -> None:
    built, _, _ = runner()

    with pytest.raises(InvalidPayload):
        await built.handle_send(raw)


def callback(source: bytes) -> bytes:
    return json.dumps(
        {"status": 500, "sourceBody": base64.b64encode(source).decode()}
    ).encode()


async def test_the_failure_callback_marks_the_row_failed_and_reports(monkeypatch):
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)
    built, outbox, _ = runner(SHIPPED)

    await built.handle_exhausted(callback(body(SHIPPED)))

    assert outbox.finished == [(SHIPPED, EmailStatus.FAILED)]
    assert [str(error) for error in reported] == ["order_shipped: retries exhausted"]


async def test_a_late_failure_callback_changes_nothing(monkeypatch) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)
    built, outbox, _ = runner()

    await built.handle_exhausted(callback(body(SHIPPED)))

    assert outbox.finished == []
    assert reported == []


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b'{"sourceBody": 5}',
        b'{"sourceBody": "***"}',
        callback(b'{"store_id": "s"}'),
    ],
)
async def test_a_bad_failure_callback_is_an_invalid_payload(raw: bytes) -> None:
    built, _, _ = runner()

    with pytest.raises(InvalidPayload):
        await built.handle_exhausted(raw)


async def test_logs_carry_ids_and_kind_but_no_address_subject_or_body(
    caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(order_email_job, "report_exception", lambda error: None)
    override = TemplateText("Secret subject $order_id", "Secret body text")
    for job, error in (
        (CONFIRM, None),
        (SHIPPED, EmailRejected()),
        (ALERT, EmailDeliveryFailed()),
    ):
        sender = RecordingSender(
            {CUSTOMER: error, "owner@example.com": error} if error else {}
        )
        built, _, _ = runner(
            job, override=None if job is ALERT else override, sender=sender
        )
        try:
            await built.handle_send(body(job))
        except SendFailed:
            pass

    text = caplog.text + " ".join(str(vars(r)) for r in caplog.records)
    for secret in (CUSTOMER, "owner@example.com", "Secret subject", "Secret body"):
        assert secret not in text
    assert ORDER_ID in text


async def test_a_crash_while_settling_asks_for_a_retry(monkeypatch) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)
    built, outbox, sender = runner(CONFIRM)

    async def broken_finish(job: OrderEmailJob, status: EmailStatus) -> bool:
        raise RuntimeError("connection lost")

    monkeypatch.setattr(outbox, "finish", broken_finish)

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert len(sender.sent) == 1  # a retry is deduplicated by the idempotency key
    assert [str(error) for error in reported] == ["order_confirmation: RuntimeError"]


async def test_a_crash_while_counting_an_attempt_still_asks_for_a_retry(
    monkeypatch,
) -> None:
    reported: list[BaseException] = []
    monkeypatch.setattr(order_email_job, "report_exception", reported.append)
    sender = RecordingSender({CUSTOMER: EmailDeliveryFailed()})
    built, outbox, _ = runner(CONFIRM, sender=sender)

    async def broken_attempt(job: OrderEmailJob) -> None:
        raise RuntimeError("connection lost")

    monkeypatch.setattr(outbox, "count_attempt", broken_attempt)

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert [str(error) for error in reported] == ["order_confirmation: RuntimeError"]
