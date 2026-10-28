"""QStash callbacks that send order emails (KAN-81): signature, payload, retry semantics.

Built from ``create_app()`` so the real mounting, error envelope and OpenAPI exclusion are
exercised. The runner works on fakes; its behaviour is covered in the service tests.
"""

import base64
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from app.api.v1.internal_order_emails import get_order_email_runner
from app.core.config import settings
from app.main import create_app
from app.repositories.order_email_context import StoreEmailContext
from app.services.email import EmailDeliveryFailed
from app.services.order_email_job import (
    FAILED_PATH,
    SEND_PATH,
    EmailStatus,
    OrderEmailJob,
)
from app.services.order_email_runner import OrderEmailRunner, PendingEmail
from app.services.order_email_templates import OrderEmailKind, OrderFacts
from tests.fakes_email import FakeDirectory, FakeOutbox, RecordingSender
from tests.qstash_tokens import make_token

BASE = "https://api.example.test"
KEY = "current-signing-key-for-tests"
STORE_ID = "abcdefgh12345678abcdefgh"
JOB = OrderEmailJob(STORE_ID, "order1", OrderEmailKind.ORDER_CONFIRMATION)
BODY = JOB.payload().encode()
CUSTOMER = "shopper@example.com"


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROVISIONING_BASE_URL", BASE)
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", SecretStr(KEY))
    monkeypatch.setattr(settings, "QSTASH_NEXT_SIGNING_KEY", None)


@pytest.fixture
def outbox() -> FakeOutbox:
    facts = OrderFacts("order1", "GBP", 100, (), None, None)
    return FakeOutbox({JOB: PendingEmail(facts, CUSTOMER, None)})


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
async def client(
    outbox: FakeOutbox, sender: RecordingSender
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    runner = OrderEmailRunner(
        outbox, FakeDirectory(StoreEmailContext("Shop", "org1")), sender, None
    )
    app.dependency_overrides[get_order_email_runner] = lambda: runner
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        yield http


def signed(body: bytes, path: str = SEND_PATH) -> dict[str, str]:
    return {"Upstash-Signature": make_token(body, f"{BASE}{path}", KEY)}


async def test_a_signed_delivery_sends_the_email(
    client: httpx.AsyncClient, outbox: FakeOutbox, sender: RecordingSender
) -> None:
    response = await client.post(SEND_PATH, content=BODY, headers=signed(BODY))

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert [m.to for m in sender.sent] == [CUSTOMER]
    assert outbox.finished == [(JOB, EmailStatus.SENT)]


async def test_a_repeated_delivery_sends_nothing_more(
    client: httpx.AsyncClient, sender: RecordingSender
) -> None:
    for _ in range(2):
        response = await client.post(SEND_PATH, content=BODY, headers=signed(BODY))
        assert response.status_code == 200

    assert len(sender.sent) == 1


@pytest.mark.parametrize("path", [SEND_PATH, FAILED_PATH])
async def test_an_unsigned_or_misdirected_delivery_is_refused(
    client: httpx.AsyncClient, sender: RecordingSender, path: str
) -> None:
    other = FAILED_PATH if path == SEND_PATH else SEND_PATH

    unsigned = await client.post(path, content=BODY)
    misdirected = await client.post(path, content=BODY, headers=signed(BODY, other))

    assert unsigned.status_code == misdirected.status_code == 401
    assert sender.sent == []


async def test_a_transient_failure_is_a_500_so_qstash_retries(
    client: httpx.AsyncClient, outbox: FakeOutbox, sender: RecordingSender
) -> None:
    sender.errors[CUSTOMER] = EmailDeliveryFailed()

    response = await client.post(SEND_PATH, content=BODY, headers=signed(BODY))

    assert response.status_code == 500
    assert response.json() == {"success": False, "error": "Order email not sent"}
    assert outbox.attempts == [JOB]


@pytest.mark.parametrize("path", [SEND_PATH, FAILED_PATH])
async def test_a_bad_payload_is_a_non_retryable_400(
    client: httpx.AsyncClient, path: str
) -> None:
    body = b'{"store_id": "x"}'

    response = await client.post(path, content=body, headers=signed(body, path))

    assert response.status_code == 400
    assert response.headers["Upstash-NonRetryable-Error"] == "true"


async def test_the_failure_callback_marks_the_row_failed(
    client: httpx.AsyncClient, outbox: FakeOutbox
) -> None:
    body = json.dumps({"sourceBody": base64.b64encode(BODY).decode()}).encode()

    response = await client.post(
        FAILED_PATH, content=body, headers=signed(body, FAILED_PATH)
    )

    assert response.status_code == 200
    assert outbox.finished == [(JOB, EmailStatus.FAILED)]


async def test_the_routes_are_not_in_the_openapi_schema() -> None:
    paths = create_app().openapi()["paths"]

    assert not any(path.startswith("/internal/order-emails") for path in paths)


def test_the_runner_dependency_builds_the_sql_runner() -> None:
    from app.services.order_email_runner import (
        SqlOrderEmailDirectory,
        SqlOrderEmailOutbox,
    )
    from tests.fakes import FakeSession, FakeSessionProvider, as_provider

    runner = get_order_email_runner(
        as_provider(FakeSessionProvider(FakeSession())), RecordingSender()
    )

    assert isinstance(runner.outbox, SqlOrderEmailOutbox)
    assert isinstance(runner.directory, SqlOrderEmailDirectory)
