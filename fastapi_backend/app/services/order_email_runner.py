"""Sending one order email outbox row (KAN-81). No FastAPI imports.

``POST /internal/order-emails/send`` hands the QStash job to ``OrderEmailRunner.send``: only a
``pending`` row is sent, then settled with a conditional update. Resend gets an idempotency key
per order and kind (per recipient for the alert), so a retried delivery never sends twice.

* ``sent``: every message accepted.
* ``skipped``: email disabled, no shopper address, or no alert recipient.
* ``failed``: Resend refused a message for good (reported to Sentry), or QStash ran out of
  retries (the failure callback, reported to Sentry).
* A transient Resend error or timeout counts an attempt and raises ``SendFailed`` (500), so
  QStash retries. Retryable failures are logged only; Sentry hears about them once, when the
  retries run out.

Logs and Sentry events carry ids, the kind and exception class names only: never an address,
a subject or a body.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.order_email_job import (
    EmailStatus,
    OrderEmailFailed,
    OrderEmailJob,
    SendFailed,
    job_from_body,
    job_from_failure_callback,
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

logger = logging.getLogger("storecart.order_emails")

SEND_TIMEOUT_SECONDS = 5.0  # per message; the alert's messages go out concurrently
MAX_ALERT_RECIPIENTS = 20


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

    async def status(self, job: OrderEmailJob) -> EmailStatus | None:
        """The row's current status (None when there is no row)."""

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

    async def status(self, job: OrderEmailJob) -> EmailStatus | None:
        async with self._open_store(job.store_id) as session:
            value = await OrderEmailsRepository(session).status(
                job.order_id, job.kind.value
            )
        return EmailStatus(value) if value is not None else None

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
            self._log_crash(job, exc)
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
            if len(members) > MAX_ALERT_RECIPIENTS:
                logger.warning(
                    "order email alert capped: %d recipient(s) dropped",
                    len(members) - MAX_ALERT_RECIPIENTS,
                    extra=job.log_extra(),
                )
            return [
                _Recipient(member.email, member.user_id)
                for member in members[:MAX_ALERT_RECIPIENTS]
            ]
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

    async def _send_one(self, message: EmailMessage) -> None:
        await asyncio.wait_for(self.sender.send(message), SEND_TIMEOUT_SECONDS)

    async def _deliver(
        self, job: OrderEmailJob, messages: Sequence[EmailMessage]
    ) -> EmailStatus | None:
        """Send every message at once and settle the row from the outcomes.

        Disabled email skips the row. Any transient failure retries the whole row (the
        idempotency keys make the resend of an accepted message a no-op). Otherwise one
        rejected message leaves the row ``failed``, even when the other recipients got theirs:
        a retry cannot fix the refused address.
        """
        results = await asyncio.gather(
            *(self._send_one(message) for message in messages), return_exceptions=True
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if any(isinstance(error, EmailDisabled) for error in errors):
            return await self._finish(job, EmailStatus.SKIPPED)
        transient = [error for error in errors if not isinstance(error, EmailRejected)]
        if transient:
            for error in transient:
                if not isinstance(error, EmailDeliveryFailed | TimeoutError):
                    self._log_crash(job, error)
            logger.warning(
                "order email send failed: %s",
                ", ".join(sorted({type(error).__name__ for error in transient})),
                extra=job.log_extra(),
            )
            try:
                await self.outbox.count_attempt(job)
            except Exception as exc:  # noqa: BLE001 - the retry is what matters
                self._log_crash(job, exc)
            raise SendFailed
        if errors:
            logger.error("order email rejected by the provider", extra=job.log_extra())
            report_exception(OrderEmailFailed(f"{job.kind.value}: rejected"))
            return await self._finish(job, EmailStatus.FAILED)
        return await self._finish(job, EmailStatus.SENT)

    async def _finish(
        self, job: OrderEmailJob, status: EmailStatus
    ) -> EmailStatus | None:
        """Settle the row; when another delivery settled it first, its actual state."""
        try:
            if await self.outbox.finish(job, status):
                logger.info("order email %s", status.value, extra=job.log_extra())
                return status
            actual = await self.outbox.status(job)
        except Exception as exc:  # noqa: BLE001 - retried; the idempotency key dedupes
            self._log_crash(job, exc)
            raise SendFailed from None
        logger.info(
            "order email already settled: %s",
            actual.value if actual else "missing",
            extra=job.log_extra(),
        )
        return actual

    @staticmethod
    def _log_crash(job: OrderEmailJob, exc: BaseException) -> None:
        # Class name and SQLSTATE only: a driver error's text can echo a DSN or an address.
        logger.error(
            "order email job failed: %s", safe_reason(exc), extra=job.log_extra()
        )
