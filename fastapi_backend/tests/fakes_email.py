"""Fakes for the order email job (KAN-81): sender, outbox, platform directory and enqueuer."""

from dataclasses import dataclass, field

from app.repositories.order_email_context import AlertRecipient, StoreEmailContext
from app.services.email import EmailMessage
from app.services.order_email_job import (
    EmailStatus,
    EnqueueFailed,
    OrderEmailJob,
    PendingEmail,
)


@dataclass
class RecordingSender:
    """Records every message; ``errors`` maps a recipient to the exception its send raises."""

    errors: dict[str, BaseException] = field(default_factory=dict)
    sent: list[EmailMessage] = field(default_factory=list)

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
        error = self.errors.get(message.to)
        if error is not None:
            raise error


@dataclass
class FakeOutbox:
    pending: dict[OrderEmailJob, PendingEmail] = field(default_factory=dict)
    finished: list[tuple[OrderEmailJob, EmailStatus]] = field(default_factory=list)
    attempts: list[OrderEmailJob] = field(default_factory=list)
    load_error: BaseException | None = None

    async def load_pending(self, job: OrderEmailJob) -> PendingEmail | None:
        if self.load_error is not None:
            raise self.load_error
        return self.pending.get(job)

    async def finish(self, job: OrderEmailJob, status: EmailStatus) -> bool:
        if job not in self.pending:
            return False
        del self.pending[job]
        self.finished.append((job, status))
        return True

    async def count_attempt(self, job: OrderEmailJob) -> None:
        self.attempts.append(job)


@dataclass
class FakeDirectory:
    store_context: StoreEmailContext | None = None
    recipients: list[AlertRecipient] = field(default_factory=list)

    async def store(self, store_id: str) -> StoreEmailContext | None:
        return self.store_context

    async def alert_recipients(self, organization_id: str) -> list[AlertRecipient]:
        return list(self.recipients)


@dataclass
class RecordingEnqueuer:
    """Records published jobs; ``fail`` makes every publish raise ``EnqueueFailed``."""

    fail: bool = False
    jobs: list[OrderEmailJob] = field(default_factory=list)

    async def enqueue(self, job: OrderEmailJob) -> None:
        if self.fail:
            raise EnqueueFailed
        self.jobs.append(job)
