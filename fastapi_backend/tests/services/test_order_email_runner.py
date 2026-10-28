"""Sending one order email outbox row (KAN-81), on fakes: no network, no database."""

import asyncio
import base64
import json
import logging

import pytest

from app.repositories.order_email_context import AlertRecipient, StoreEmailContext
from app.services import order_email_runner
from app.services.email import (
    EmailDeliveryFailed,
    EmailDisabled,
    EmailMessage,
    EmailRejected,
)
from app.services.order_email_job import (
    EmailStatus,
    InvalidPayload,
    OrderEmailJob,
    SendFailed,
)
from app.services.order_email_runner import (
    MAX_ALERT_RECIPIENTS,
    OrderEmailRunner,
    PendingEmail,
)
from app.services.order_email_templates import (
    OrderEmailKind,
    OrderFacts,
    OrderLine,
    TemplateText,
)
from tests.fakes_email import FakeDirectory, FakeOutbox, RecordingSender

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
    return job.payload().encode()


def callback(source: bytes) -> bytes:
    return json.dumps(
        {"status": 500, "sourceBody": base64.b64encode(source).decode()}
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


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    events: list[BaseException] = []
    monkeypatch.setattr(order_email_runner, "report_exception", events.append)
    return events


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

    assert sorted((m.to, m.idempotency_key) for m in sender.sent) == [
        ("admin@x.test", f"{ALERT.dedup_id}-u2"),
        ("owner@example.com", f"{ALERT.dedup_id}-u1"),
    ]
    assert f"{APP_URL}/dashboard/orders/{ORDER_ID}" in sender.sent[0].html
    assert outbox.finished == [(ALERT, EmailStatus.SENT)]


async def test_the_alert_recipients_are_sent_to_at_once() -> None:
    started = 0
    all_started = asyncio.Event()

    class Concurrent(RecordingSender):
        async def send(self, message: EmailMessage) -> None:
            nonlocal started
            started += 1
            if started == len(OWNERS):
                all_started.set()
            # Every send must be in flight before any finishes, or this times out.
            await asyncio.wait_for(all_started.wait(), 1)
            await super().send(message)

    built, _, sender = runner(ALERT, sender=Concurrent())

    assert await built.handle_send(body(ALERT)) is EmailStatus.SENT
    assert len(sender.sent) == len(OWNERS)


async def test_the_alert_is_capped_and_the_drop_is_logged_without_addresses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    many = [
        AlertRecipient(f"u{n:02d}", f"member{n}@x.test")
        for n in range(MAX_ALERT_RECIPIENTS + 3)
    ]
    built, _, sender = runner(ALERT, directory=FakeDirectory(STORE, many))

    await built.handle_send(body(ALERT))

    assert len(sender.sent) == MAX_ALERT_RECIPIENTS
    assert "3 recipient(s) dropped" in caplog.text
    assert "@x.test" not in caplog.text


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


async def test_a_rejected_message_fails_for_good_and_is_reported(
    reported: list[BaseException],
) -> None:
    sender = RecordingSender({CUSTOMER: EmailRejected()})
    built, outbox, _ = runner(CONFIRM, sender=sender)

    status = await built.handle_send(body(CONFIRM))

    assert status is EmailStatus.FAILED
    assert outbox.finished == [(CONFIRM, EmailStatus.FAILED)]
    assert [str(error) for error in reported] == ["order_confirmation: rejected"]


async def test_one_rejected_alert_recipient_leaves_the_row_failed_though_others_got_it(
    reported: list[BaseException],
) -> None:
    sender = RecordingSender({"owner@example.com": EmailRejected()})
    built, outbox, _ = runner(ALERT, sender=sender)

    status = await built.handle_send(body(ALERT))

    assert status is EmailStatus.FAILED
    assert sorted(m.to for m in sender.sent) == ["admin@x.test", "owner@example.com"]
    assert outbox.finished == [(ALERT, EmailStatus.FAILED)]
    assert [str(error) for error in reported] == ["new_order_alert: rejected"]


@pytest.mark.parametrize(
    "error", [EmailDeliveryFailed(), TimeoutError(), RuntimeError("odd")]
)
async def test_a_transient_failure_counts_an_attempt_and_asks_for_a_retry(
    error: BaseException, reported: list[BaseException]
) -> None:
    sender = RecordingSender({CUSTOMER: error})
    built, outbox, _ = runner(CONFIRM, sender=sender)

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert outbox.attempts == [CONFIRM]
    assert outbox.finished == []
    assert CONFIRM in outbox.pending
    assert reported == []  # Sentry hears about it once the retries run out


async def test_a_slow_provider_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(order_email_runner, "SEND_TIMEOUT_SECONDS", 0.01)

    class Slow(RecordingSender):
        async def send(self, message: EmailMessage) -> None:
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

    # The other recipient still got it; its idempotency key dedupes the retry.
    assert len(sender.sent) == 2
    assert outbox.attempts == [ALERT]


async def test_two_concurrent_deliveries_send_with_one_key_and_settle_once() -> None:
    both_sending = asyncio.Barrier(2)

    class InFlightTogether(RecordingSender):
        async def send(self, message: EmailMessage) -> None:
            await super().send(message)
            await asyncio.wait_for(both_sending.wait(), 1)

    built, outbox, sender = runner(CONFIRM, sender=InFlightTogether())
    finished: list[bool] = []
    original = outbox.finish

    async def recording_finish(job: OrderEmailJob, status: EmailStatus) -> bool:
        changed = await original(job, status)
        finished.append(changed)
        return changed

    outbox.finish = recording_finish  # type: ignore[method-assign]

    first, second = await asyncio.gather(built.send(CONFIRM), built.send(CONFIRM))

    assert {m.idempotency_key for m in sender.sent} == {CONFIRM.dedup_id}
    assert len(sender.sent) == 2  # Resend delivers the second as a replay of the first
    assert sorted(finished) == [False, True]
    assert first is second is EmailStatus.SENT  # the loser reports the actual state


async def test_a_row_settled_by_another_delivery_reports_its_actual_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    built, outbox, _ = runner(CONFIRM)
    original = outbox.finish

    async def settled_meanwhile(job: OrderEmailJob, status: EmailStatus) -> bool:
        await original(job, EmailStatus.FAILED)  # the failure callback won the race
        return False

    outbox.finish = settled_meanwhile  # type: ignore[method-assign]

    assert await built.send(CONFIRM) is EmailStatus.FAILED
    assert "already settled: failed" in caplog.text


async def test_a_store_read_failure_asks_for_a_retry_and_logs_only_the_class(
    caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)
    built, outbox, _ = runner(CONFIRM)
    outbox.load_error = RuntimeError("postgresql://user:secret@host/db")

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert reported == []
    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text


async def test_a_crash_while_settling_asks_for_a_retry(
    monkeypatch: pytest.MonkeyPatch, reported: list[BaseException]
) -> None:
    built, outbox, sender = runner(CONFIRM)

    async def broken_finish(job: OrderEmailJob, status: EmailStatus) -> bool:
        raise RuntimeError("connection lost")

    monkeypatch.setattr(outbox, "finish", broken_finish)

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))

    assert len(sender.sent) == 1  # a retry is deduplicated by the idempotency key
    assert reported == []


async def test_a_crash_while_counting_an_attempt_still_asks_for_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingSender({CUSTOMER: EmailDeliveryFailed()})
    built, outbox, _ = runner(CONFIRM, sender=sender)

    async def broken_attempt(job: OrderEmailJob) -> None:
        raise RuntimeError("connection lost")

    monkeypatch.setattr(outbox, "count_attempt", broken_attempt)

    with pytest.raises(SendFailed):
        await built.handle_send(body(CONFIRM))


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"store_id": 1}'])
async def test_a_bad_delivery_is_an_invalid_payload(raw: bytes) -> None:
    built, _, _ = runner()

    with pytest.raises(InvalidPayload):
        await built.handle_send(raw)


async def test_the_failure_callback_marks_the_row_failed_and_reports(
    reported: list[BaseException],
) -> None:
    built, outbox, _ = runner(SHIPPED)

    await built.handle_exhausted(callback(body(SHIPPED)))

    assert outbox.finished == [(SHIPPED, EmailStatus.FAILED)]
    assert [str(error) for error in reported] == ["order_shipped: retries exhausted"]


async def test_a_late_failure_callback_changes_nothing(
    reported: list[BaseException],
) -> None:
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
    caplog: pytest.LogCaptureFixture, reported: list[BaseException]
) -> None:
    caplog.set_level(logging.DEBUG)
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
    text += " ".join(str(error) for error in reported)
    for secret in (CUSTOMER, "owner@example.com", "Secret subject", "Secret body"):
        assert secret not in text
    assert ORDER_ID in text


async def test_a_cancelled_send_propagates_instead_of_counting_an_attempt() -> None:
    sender = RecordingSender({"owner@example.com": asyncio.CancelledError()})
    built, outbox, _ = runner(ALERT, sender=sender)

    with pytest.raises(asyncio.CancelledError):
        await built.handle_send(body(ALERT))

    assert outbox.attempts == []
    assert outbox.finished == []
