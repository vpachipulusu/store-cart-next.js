"""Order email jobs and their QStash publisher (KAN-81, ADR-009). No FastAPI imports.

A job names one outbox row by ids only (``store_id``, ``order_id``, ``kind``; never an
address). After the store commit that wrote the row (``order_email_record``), the job is
published to QStash, deduplicated per order and kind, and QStash calls
``POST /internal/order-emails/send`` (``order_email_runner``) to send it.

* The webhook re-raises a publish failure that a retry can fix (timeout, network, 5xx, 429):
  the webhook answers 500, Stripe redelivers, and the redelivery that finds the order already
  paid re-publishes every row still ``pending``. QStash refusing the request itself (any
  other 4xx: a bad token or destination) is a misconfiguration: it is logged and reported,
  never a 500, and the row stays ``pending``.
* Fulfilment only logs and reports a publish failure; the row stays ``pending``.
* Without QStash nothing is published; outside local and test that is an error and a Sentry
  event, since no order email can go out.

Logs and Sentry events carry ids, the kind and exception class names only.
"""

import asyncio
import base64
import binascii
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.sentry import report_exception
from app.services.order_email_templates import OrderEmailKind
from app.services.store_provisioning import InvalidStoreId, database_name_for

logger = logging.getLogger("storecart.order_emails")

SEND_PATH = "/internal/order-emails/send"
FAILED_PATH = "/internal/order-emails/failed"
ORDER_EMAIL_RETRIES = 3
PUBLISH_TIMEOUT_SECONDS = 3.0
PAID_KINDS = (OrderEmailKind.ORDER_CONFIRMATION, OrderEmailKind.NEW_ORDER_ALERT)
ORDER_ID_PATTERN = re.compile(r"[A-Za-z0-9]{1,64}")
JOB_KEYS = frozenset({"store_id", "order_id", "kind"})
PUBLISHED = frozenset({200, 201, 202})


class EmailStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


class EnqueueFailed(Exception):
    """QStash did not take the message, and a retry may fix it. Carries no token or URL."""


class InvalidPayload(Exception):
    """A signed delivery whose body is not an order email job."""


class SendFailed(Exception):
    """A send worth retrying failed (the route answers 500)."""


class OrderEmailFailed(Exception):
    """For Sentry: an order email problem. The message is a kind or reason, never PII."""


@dataclass(frozen=True)
class OrderEmailJob:
    store_id: str
    order_id: str
    kind: OrderEmailKind

    def payload(self) -> str:
        return json.dumps(
            {
                "store_id": self.store_id,
                "order_id": self.order_id,
                "kind": self.kind.value,
            }
        )

    @property
    def dedup_id(self) -> str:
        return f"order-email-{self.store_id}-{self.order_id}-{self.kind.value}"

    def idempotency_key(self, recipient_id: str | None = None) -> str:
        return f"{self.dedup_id}-{recipient_id}" if recipient_id else self.dedup_id

    def log_extra(self) -> dict[str, str]:
        return {
            "store_id": self.store_id,
            "order_id": self.order_id,
            "kind": self.kind.value,
        }


def is_valid_store_id(store_id: str) -> bool:
    """A store id has the shape of a real one (the store database name is built from it)."""
    try:
        database_name_for(store_id)
    except InvalidStoreId:
        return False
    return True


def parse_job(raw: Any) -> OrderEmailJob | None:
    """The job a delivered body names, or None when it is not exactly a valid job."""
    if not isinstance(raw, dict) or set(raw) != JOB_KEYS:
        return None
    store_id, order_id, kind = raw["store_id"], raw["order_id"], raw["kind"]
    if not all(isinstance(value, str) for value in (store_id, order_id, kind)):
        return None
    if not ORDER_ID_PATTERN.fullmatch(order_id) or not is_valid_store_id(store_id):
        return None
    try:
        return OrderEmailJob(store_id, order_id, OrderEmailKind(kind))
    except ValueError:
        return None


def _loads(raw: bytes | str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        raise InvalidPayload from None


def job_from_body(raw: bytes) -> OrderEmailJob:
    job = parse_job(_loads(raw))
    if job is None:
        raise InvalidPayload
    return job


def job_from_failure_callback(raw: bytes) -> OrderEmailJob:
    """The job of a QStash failure callback (its ``sourceBody`` is the base64 original)."""
    callback = _loads(raw)
    encoded = callback.get("sourceBody") if isinstance(callback, dict) else None
    if not isinstance(encoded, str):
        raise InvalidPayload
    try:
        source = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidPayload from None
    return job_from_body(source)


# --- publishing -------------------------------------------------------------------------


class OrderEmailEnqueuer(Protocol):
    async def enqueue(self, job: OrderEmailJob) -> None:
        """Publish one job; raise EnqueueFailed when a retry may still get it published."""


class DisabledOrderEmailEnqueuer:
    """QStash is not configured: nothing is published and the row stays ``pending``.

    Never raises, so a payment webhook is still acknowledged. Outside local and test the
    log line is an error and a Sentry event, since no order email can go out.
    """

    def __init__(self, *, relaxed: bool = True) -> None:
        self._relaxed = relaxed

    async def enqueue(self, job: OrderEmailJob) -> None:
        level = logging.WARNING if self._relaxed else logging.ERROR
        logger.log(
            level,
            "qstash not configured: order email not enqueued",
            extra=job.log_extra(),
        )
        if not self._relaxed:
            report_exception(OrderEmailFailed("qstash not configured"))


class QStashOrderEmailEnqueuer:
    """Publishes jobs to QStash (``POST {QSTASH_URL}/v2/publish/{destination}``)."""

    def __init__(
        self,
        token: str,
        base_url: str,
        callback_base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._base = base_url.rstrip("/")
        self._callback = callback_base_url.rstrip("/")
        self._client = client

    async def _post(self, url: str, headers: dict[str, str], body: str) -> int:
        if self._client is not None:
            response = await self._client.post(
                url, headers=headers, content=body, timeout=PUBLISH_TIMEOUT_SECONDS
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers=headers, content=body, timeout=PUBLISH_TIMEOUT_SECONDS
                )
        return response.status_code

    async def enqueue(self, job: OrderEmailJob) -> None:
        destination = f"{self._callback}{SEND_PATH}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Upstash-Retries": str(ORDER_EMAIL_RETRIES),
            "Upstash-Failure-Callback": f"{self._callback}{FAILED_PATH}",
            # A second publish for the same order and kind collapses into one delivery.
            "Upstash-Deduplication-Id": job.dedup_id,
        }
        url = f"{self._base}/v2/publish/{quote(destination, safe=':/')}"
        try:
            status = await self._post(url, headers, job.payload())
        except httpx.HTTPError as exc:
            logger.error(
                "order email publish failed: %s",
                type(exc).__name__,
                extra=job.log_extra(),
            )
            raise EnqueueFailed from None
        if status in PUBLISHED:
            return
        if status == 429 or status >= 500:
            logger.error(
                "order email publish failed: status=%s", status, extra=job.log_extra()
            )
            raise EnqueueFailed
        # QStash refused the request itself (token, destination): retrying cannot help, and
        # a 500 here would fail every payment webhook until someone fixes the settings.
        logger.error(
            "order email publish refused; row left pending: status=%s",
            status,
            extra=job.log_extra(),
        )
        report_exception(OrderEmailFailed(f"qstash refused the publish: {status}"))


def build_order_email_enqueuer(settings: Settings) -> OrderEmailEnqueuer:
    """QStash when ``QSTASH_TOKEN`` and ``PROVISIONING_BASE_URL`` are set, else disabled."""
    token = settings.QSTASH_TOKEN
    if token is not None and settings.PROVISIONING_BASE_URL:
        return QStashOrderEmailEnqueuer(
            token.get_secret_value(),
            settings.QSTASH_URL,
            settings.PROVISIONING_BASE_URL,
        )
    return DisabledOrderEmailEnqueuer(relaxed=settings.relaxed_environment)


async def publish_jobs(
    enqueuer: OrderEmailEnqueuer, jobs: Sequence[OrderEmailJob]
) -> None:
    """Publish every job at once (the webhook waits one timeout, not one per job); then
    EnqueueFailed when any one was not accepted."""
    results = await asyncio.gather(
        *(enqueuer.enqueue(job) for job in jobs), return_exceptions=True
    )
    errors = [result for result in results if isinstance(result, BaseException)]
    for error in errors:
        if not isinstance(error, EnqueueFailed):
            raise error
    if errors:
        raise EnqueueFailed


async def publish_quietly(
    enqueuer: OrderEmailEnqueuer, jobs: Sequence[OrderEmailJob]
) -> None:
    """Publish, and only log and report a failure: the caller's change is already committed."""
    for job in jobs:
        try:
            await enqueuer.enqueue(job)
        except Exception as exc:  # noqa: BLE001 - the order change must still succeed
            reason = type(exc).__name__
            logger.error(
                "order email publish failed; row left pending: %s",
                reason,
                extra=job.log_extra(),
            )
            report_exception(OrderEmailFailed(f"{job.kind.value}: {reason}"))
