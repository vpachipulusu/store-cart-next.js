"""Order emails through an outbox and QStash (KAN-81, ADR-009). No FastAPI imports.

Writing: the outbox rows (``order_emails``) are inserted in the store transaction that changed
the order, ``ON CONFLICT DO NOTHING``: the confirmation and the new-order alert when the
Connect webhook moved the order to ``paid``, the shipped notice when the merchant fulfilled it.
Those writes run in a SAVEPOINT (``record_order_emails``), so a store database still before
revision 0012 confirms its payment or fulfilment as before and only logs "email skipped".

Publishing: after the store commit, one QStash message per row carries ids only
(``store_id``, ``order_id``, ``kind``; never an address), deduplicated per order and kind. The
webhook re-raises a publish failure (Stripe redelivers, and a redelivery that finds the order
already paid re-publishes the rows still ``pending``); fulfilment logs and reports it and the
row stays ``pending``.

Sending (``OrderEmailRunner``, called by ``POST /internal/order-emails/send``): only a
``pending`` row is sent, then settled with a conditional update. Resend gets an idempotency key
per order and kind (per recipient for the alert), so a retried delivery never sends twice.

* ``sent``: every message accepted.
* ``skipped``: email disabled, no shopper address, no alert recipient, or the store is gone.
* ``failed``: Resend refused a message for good, or QStash ran out of retries (failure
  callback). Both are reported to Sentry.
* a transient Resend error or timeout counts an attempt and raises ``SendFailed`` (500), so
  QStash retries.

Logs and Sentry events carry ids, the kind and exception class names only: never an address,
a subject or a body.
"""

import asyncio
import base64
import binascii
import json
import logging
import re
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.sentry import report_exception
from app.repositories.order_email_context import (
    AlertRecipient,
    OrderEmailContextRepository,
    StoreEmailContext,
)
from app.repositories.order_emails import OrderEmailsRepository
from app.services.email import (
    EmailDeliveryFailed,
    EmailDisabled,
    EmailMessage,
    EmailRejected,
    EmailSender,
)
from app.services.order_email_templates import (
    OrderEmailKind,
    OrderFacts,
    OrderLine,
    TemplateText,
    order_url,
    render_order_email,
)
from app.services.store_migrations import safe_reason
from app.services.store_provisioning import InvalidStoreId, database_name_for

logger = logging.getLogger("storecart.order_emails")

SEND_PATH = "/internal/order-emails/send"
FAILED_PATH = "/internal/order-emails/failed"
ORDER_EMAIL_RETRIES = 3
PUBLISH_TIMEOUT_SECONDS = 3.0
SEND_TIMEOUT_SECONDS = 5.0  # per message
MAX_CUSTOMER_EMAIL_LENGTH = 254
PAID_KINDS = (OrderEmailKind.ORDER_CONFIRMATION, OrderEmailKind.NEW_ORDER_ALERT)
ORDER_ID_PATTERN = re.compile(r"[A-Za-z0-9]{1,64}")
JOB_KEYS = frozenset({"store_id", "order_id", "kind"})


class EmailStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


class EnqueueFailed(Exception):
    """QStash did not accept the message. Carries no token or URL."""


class InvalidPayload(Exception):
    """A signed delivery whose body is not an order email job."""


class SendFailed(Exception):
    """A send worth retrying failed (the route answers 500)."""


class OrderEmailFailed(Exception):
    """For Sentry: an order email will not be sent. The message is the kind and a reason."""


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


def clean_customer_email(value: object) -> str | None:
    """The shopper's address from Stripe, trimmed, or None when it cannot be stored.

    Mirrors ``ck_orders_customer_email`` (3 to 254 characters, an ``@`` after the first) and
    refuses whitespace and control characters, so the write can never fail its CHECK.
    """
    if not isinstance(value, str):
        return None
    email = value.strip()
    if not 3 <= len(email) <= MAX_CUSTOMER_EMAIL_LENGTH or "@" not in email[1:]:
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in email):
        return None
    return email


def parse_job(raw: Any) -> OrderEmailJob | None:
    """The job a delivered body names, or None when it is not exactly a valid job."""
    if not isinstance(raw, dict) or set(raw) != JOB_KEYS:
        return None
    store_id, order_id, kind = raw["store_id"], raw["order_id"], raw["kind"]
    if not all(isinstance(value, str) for value in (store_id, order_id, kind)):
        return None
    if not ORDER_ID_PATTERN.fullmatch(order_id):
        return None
    try:
        database_name_for(store_id)
        return OrderEmailJob(store_id, order_id, OrderEmailKind(kind))
    except (InvalidStoreId, ValueError):
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
        """Publish one job; raise EnqueueFailed when QStash did not accept it."""


class DisabledOrderEmailEnqueuer:
    """QStash is not configured: nothing is published and the row stays ``pending``."""

    async def enqueue(self, job: OrderEmailJob) -> None:
        logger.warning(
            "qstash not configured: order email not enqueued", extra=job.log_extra()
        )


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
        if status not in (200, 201, 202):
            logger.error(
                "order email publish rejected: status=%s", status, extra=job.log_extra()
            )
            raise EnqueueFailed


def get_order_email_enqueuer(settings: Settings) -> OrderEmailEnqueuer:
    """QStash when ``QSTASH_TOKEN`` and ``PROVISIONING_BASE_URL`` are set, else disabled."""
    token = settings.QSTASH_TOKEN
    if token is not None and settings.PROVISIONING_BASE_URL:
        return QStashOrderEmailEnqueuer(
            token.get_secret_value(),
            settings.QSTASH_URL,
            settings.PROVISIONING_BASE_URL,
        )
    return DisabledOrderEmailEnqueuer()


async def publish_jobs(
    enqueuer: OrderEmailEnqueuer, jobs: Sequence[OrderEmailJob]
) -> None:
    """Publish every job; EnqueueFailed afterwards when any one was not accepted."""
    failed = False
    for job in jobs:
        try:
            await enqueuer.enqueue(job)
        except EnqueueFailed:
            failed = True
    if failed:
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


# --- the store transaction --------------------------------------------------------------


async def record_order_emails(
    session: AsyncSession,
    *,
    store_id: str,
    order_id: str,
    kinds: Sequence[OrderEmailKind],
    customer_email: str | None = None,
) -> list[OrderEmailKind]:
    """Write the outbox rows (and the shopper's address) in a SAVEPOINT; the kinds added.

    Runs inside the caller's transaction, which it never commits. A store database without
    the 0012 tables rolls back only the savepoint: the order change around it still commits.
    """
    try:
        async with session.begin_nested():
            repository = OrderEmailsRepository(session)
            if customer_email is not None:
                await repository.set_customer_email(order_id, customer_email)
            added = await repository.insert(order_id, [kind.value for kind in kinds])
    except DBAPIError as exc:
        logger.warning(
            "order email skipped: %s",
            type(exc).__name__,
            extra={"store_id": store_id, "order_id": order_id},
        )
        return []
    return [OrderEmailKind(kind) for kind in added]


async def pending_jobs(
    session: AsyncSession,
    *,
    store_id: str,
    order_id: str,
    kinds: Sequence[OrderEmailKind],
) -> list[OrderEmailJob]:
    """The jobs of ``kinds`` still ``pending`` for the order (none on a pre-0012 store)."""
    try:
        async with session.begin_nested():
            found = await OrderEmailsRepository(session).pending_kinds(
                order_id, [kind.value for kind in kinds]
            )
    except DBAPIError as exc:
        logger.warning(
            "order email skipped: %s",
            type(exc).__name__,
            extra={"store_id": store_id, "order_id": order_id},
        )
        return []
    return [OrderEmailJob(store_id, order_id, OrderEmailKind(kind)) for kind in found]


# --- sending ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingEmail:
    facts: OrderFacts
    customer_email: str | None
    override: TemplateText | None


class OrderEmailOutbox(Protocol):
    async def load_pending(self, job: OrderEmailJob) -> PendingEmail | None:
        """The order behind a ``pending`` row, or None when the row is not pending."""

    async def finish(self, job: OrderEmailJob, status: EmailStatus) -> bool:
        """``pending`` becomes ``status``; False when it was no longer pending."""

    async def count_attempt(self, job: OrderEmailJob) -> None: ...


class OrderEmailDirectory(Protocol):
    async def store(self, store_id: str) -> StoreEmailContext | None: ...

    async def alert_recipients(self, organization_id: str) -> list[AlertRecipient]: ...


StoreOpener = Callable[[str], AbstractAsyncContextManager[AsyncSession]]
PlatformOpener = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlOrderEmailOutbox:
    """The outbox in each store database, opened per call and never held across a send."""

    def __init__(self, open_store: StoreOpener) -> None:
        self._open_store = open_store

    async def load_pending(self, job: OrderEmailJob) -> PendingEmail | None:
        async with self._open_store(job.store_id) as session:
            repository = OrderEmailsRepository(session)
            if not await repository.is_pending(job.order_id, job.kind.value):
                return None
            order = await repository.order(job.order_id)
            if order is None:
                return None
            lines = await repository.lines(job.order_id)
            template = await repository.template(job.kind.value)
        facts = OrderFacts(
            order_id=order.id,
            currency=order.currency,
            total_minor=order.total_minor,
            lines=tuple(
                OrderLine(
                    line.product_name,
                    line.variant_label,
                    line.quantity,
                    line.unit_price_minor,
                )
                for line in lines
            ),
            tracking_number=order.tracking_number,
            carrier=order.carrier,
        )
        override = (
            TemplateText(template.subject, template.body_text) if template else None
        )
        return PendingEmail(facts, order.customer_email, override)

    async def finish(self, job: OrderEmailJob, status: EmailStatus) -> bool:
        async with self._open_store(job.store_id) as session:
            changed = await OrderEmailsRepository(session).finish(
                job.order_id, job.kind.value, status.value
            )
            await session.commit()
        return changed

    async def count_attempt(self, job: OrderEmailJob) -> None:
        async with self._open_store(job.store_id) as session:
            await OrderEmailsRepository(session).count_attempt(
                job.order_id, job.kind.value
            )
            await session.commit()


class SqlOrderEmailDirectory:
    """Platform reads, each in its own short session."""

    def __init__(self, open_platform: PlatformOpener) -> None:
        self._open_platform = open_platform

    async def store(self, store_id: str) -> StoreEmailContext | None:
        async with self._open_platform() as session:
            return await OrderEmailContextRepository(session).store(store_id)

    async def alert_recipients(self, organization_id: str) -> list[AlertRecipient]:
        async with self._open_platform() as session:
            return await OrderEmailContextRepository(session).alert_recipients(
                organization_id
            )


@dataclass(frozen=True)
class _Recipient:
    email: str
    user_id: str | None  # the alert's member; None for the shopper


@dataclass(frozen=True)
class OrderEmailRunner:
    """Sends one outbox row. Collaborators are injected so tests need no network or database."""

    outbox: OrderEmailOutbox
    directory: OrderEmailDirectory
    sender: EmailSender
    app_url: str | None

    async def handle_send(self, raw_body: bytes) -> EmailStatus | None:
        """Send the job a QStash delivery names. InvalidPayload or SendFailed on error."""
        return await self.send(job_from_body(raw_body))

    async def handle_exhausted(self, raw_body: bytes) -> None:
        """QStash gave up on a job (failure callback): a still pending row becomes failed."""
        job = job_from_failure_callback(raw_body)
        if await self.directory.store(job.store_id) is None:
            return  # the store (and its database) is gone: nothing to mark
        if await self.outbox.finish(job, EmailStatus.FAILED):
            logger.error("order email failed: retries exhausted", extra=job.log_extra())
            report_exception(OrderEmailFailed(f"{job.kind.value}: retries exhausted"))

    async def send(self, job: OrderEmailJob) -> EmailStatus | None:
        """Send a ``pending`` row and settle it; None when it was not pending.

        The store is looked up on the platform first: a store that no longer exists has no
        database to open, so its job ends here instead of being retried.
        """
        try:
            store = await self.directory.store(job.store_id)
            if store is None:
                logger.info(
                    "order email dropped: store not found", extra=job.log_extra()
                )
                return None
            pending = await self.outbox.load_pending(job)
            if pending is None:
                logger.info(
                    "order email not pending: nothing sent", extra=job.log_extra()
                )
                return None
            recipients = await self._recipients(job, pending, store)
        except Exception as exc:  # noqa: BLE001 - any read failure is retried
            self._report_crash(job, exc)
            raise SendFailed from None
        if not recipients:
            logger.info("order email skipped: no recipient", extra=job.log_extra())
            return await self._finish(job, EmailStatus.SKIPPED)
        messages = [self._message(job, pending, store, r) for r in recipients]
        return await self._deliver(job, messages)

    async def _recipients(
        self, job: OrderEmailJob, pending: PendingEmail, store: StoreEmailContext
    ) -> list[_Recipient]:
        if job.kind is OrderEmailKind.NEW_ORDER_ALERT:
            members = await self.directory.alert_recipients(store.organization_id)
            return [_Recipient(member.email, member.user_id) for member in members]
        if pending.customer_email is None:
            return []
        return [_Recipient(pending.customer_email, None)]

    def _message(
        self,
        job: OrderEmailJob,
        pending: PendingEmail,
        store: StoreEmailContext,
        recipient: _Recipient,
    ) -> EmailMessage:
        rendered = render_order_email(
            job.kind,
            store_id=job.store_id,
            store_name=store.name,
            facts=pending.facts,
            override=pending.override,
            link=order_url(self.app_url, job.order_id),
        )
        return EmailMessage(
            to=recipient.email,
            subject=rendered.subject,
            text=rendered.text,
            html=rendered.html,
            kind=job.kind.value,
            idempotency_key=job.idempotency_key(recipient.user_id),
        )

    async def _deliver(
        self, job: OrderEmailJob, messages: Sequence[EmailMessage]
    ) -> EmailStatus | None:
        retry = rejected = False
        for message in messages:
            try:
                await asyncio.wait_for(self.sender.send(message), SEND_TIMEOUT_SECONDS)
            except EmailDisabled:
                return await self._finish(job, EmailStatus.SKIPPED)
            except EmailRejected:
                rejected = True
            except (EmailDeliveryFailed, TimeoutError) as exc:
                logger.warning(
                    "order email send failed: %s",
                    type(exc).__name__,
                    extra=job.log_extra(),
                )
                retry = True
        if retry:
            try:
                await self.outbox.count_attempt(job)
            except Exception as exc:  # noqa: BLE001 - the retry is what matters
                self._report_crash(job, exc)
            raise SendFailed
        if rejected:
            logger.error("order email rejected by the provider", extra=job.log_extra())
            report_exception(OrderEmailFailed(f"{job.kind.value}: rejected"))
            return await self._finish(job, EmailStatus.FAILED)
        return await self._finish(job, EmailStatus.SENT)

    async def _finish(self, job: OrderEmailJob, status: EmailStatus) -> EmailStatus:
        try:
            await self.outbox.finish(job, status)
        except Exception as exc:  # noqa: BLE001 - retried; the idempotency key dedupes
            self._report_crash(job, exc)
            raise SendFailed from None
        logger.info("order email %s", status.value, extra=job.log_extra())
        return status

    @staticmethod
    def _report_crash(job: OrderEmailJob, exc: BaseException) -> None:
        logger.error(
            "order email job failed: %s", type(exc).__name__, extra=job.log_extra()
        )
        # Class name and SQLSTATE only: a driver error's text can echo a DSN.
        report_exception(OrderEmailFailed(f"{job.kind.value}: {safe_reason(exc)}"))
