"""Store provisioning as a chain of QStash steps (KAN-56, ADR-005).

Creating a store enqueues ``create_database``. Each step runs in its own function
invocation (QStash calls ``POST /internal/provisioning/step``), does one thing, and on
success publishes the next one:

1. ``create_database``: ask the ``DatabaseProvisioner`` for the store database, encrypt
   its connection string onto the store (KAN-53) and record ``database_ref``.
2. ``run_migrations``: bring the store database to the ``alembic_store`` head (KAN-57).
3. ``mark_ready``: ``PROVISIONING`` becomes ``ACTIVE``.

Rules:

* Idempotent: every step first checks the store is still ``PROVISIONING`` (a duplicate or
  late delivery is a no-op), the provisioner and the migration runner are idempotent, and
  the string ``create_database`` returns always replaces the stored one: each call sets a
  new password on the store's role (KAN-238), so the previous string no longer works.
* Retries: a transient failure raises ``StepFailed``; the route answers 500 and QStash
  redelivers with backoff (a provider that is not configured yet is retried too). A
  permanent one (bad id, unusable encryption key) marks the store ``FAILED`` at once. When the retries run out QStash calls the failure callback,
  which marks the store ``FAILED`` as well.
* Payloads and logs carry the store id and step name only: never a connection string, key
  or token. Failures log the exception class name, not its text.
"""

import base64
import binascii
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SessionProvider
from app.core.sentry import report_exception
from app.core.store_crypto import StoreSecretUnavailable
from app.models.platform.store import Store, StoreStatus
from app.services import store_secrets
from app.services.store_migrations import (
    StoreMigrationFailed,
    migrate_store,
    safe_reason,
)
from app.services.store_provisioning import (
    DatabaseProvisioner,
    InvalidStoreId,
    database_name_for,
)

logger = logging.getLogger("storecart.store_provisioning_job")

STEP_PATH = "/internal/provisioning/step"
FAILED_PATH = "/internal/provisioning/failed"
PUBLISH_TIMEOUT_SECONDS = 10.0


class Step(StrEnum):
    CREATE_DATABASE = "create_database"
    RUN_MIGRATIONS = "run_migrations"
    MARK_READY = "mark_ready"


NEXT_STEP: dict[Step, Step | None] = {
    Step.CREATE_DATABASE: Step.RUN_MIGRATIONS,
    Step.RUN_MIGRATIONS: Step.MARK_READY,
    Step.MARK_READY: None,
}


class EnqueueFailed(Exception):
    """The step could not be handed to QStash. Carries no token or URL."""


class StepFailed(Exception):
    """A step failed in a way worth retrying (the route answers 500)."""


class StepAbandoned(Exception):
    """A step can never succeed (the store is marked FAILED, no retry)."""


class InvalidPayload(Exception):
    """A signed delivery whose body is not a valid step or failure callback."""


MAX_ATTEMPT = 1000


def _dedup_id(store_id: str, step: Step, attempt: int) -> str:
    """One id per run (``attempt`` 0 is the first run, then each admin re-run) and step,
    so an earlier publish of the same step can never collapse a re-run's."""
    return f"provision-{store_id}-{step.value}-a{attempt}"


class StepEnqueuer(Protocol):
    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        """Publish one step; raise EnqueueFailed when QStash did not accept it."""


class NoopEnqueuer:
    """Local and test default when QStash is not configured: nothing is published."""

    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        logger.warning(
            "qstash not configured: provisioning step not enqueued",
            extra={"store_id": store_id, "step": step.value, "attempt": attempt},
        )


class UnconfiguredEnqueuer:
    """Outside local/test without QSTASH_TOKEN and PROVISIONING_BASE_URL."""

    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        logger.error(
            "QSTASH_TOKEN and PROVISIONING_BASE_URL are not set",
            extra={"store_id": store_id},
        )
        raise EnqueueFailed


class QStashEnqueuer:
    """Publishes steps to QStash (``POST {QSTASH_URL}/v2/publish/{destination}``)."""

    def __init__(
        self,
        token: str,
        base_url: str,
        callback_base_url: str,
        *,
        retries: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._base = base_url.rstrip("/")
        self._callback = callback_base_url.rstrip("/")
        self._retries = retries
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

    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        destination = f"{self._callback}{STEP_PATH}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Upstash-Retries": str(self._retries),
            "Upstash-Failure-Callback": f"{self._callback}{FAILED_PATH}",
            # A duplicate publish of the same step collapses into one delivery.
            "Upstash-Deduplication-Id": _dedup_id(store_id, step, attempt),
        }
        body = json.dumps(
            {"store_id": store_id, "step": step.value, "attempt": attempt}
        )
        url = f"{self._base}/v2/publish/{quote(destination, safe=':/')}"
        try:
            status = await self._post(url, headers, body)
        except httpx.HTTPError as exc:
            logger.error(
                "qstash publish failed: %s",
                type(exc).__name__,
                extra={"store_id": store_id, "step": step.value},
            )
            raise EnqueueFailed from None
        if status not in (200, 201, 202):
            logger.error(
                "qstash publish rejected: status=%s",
                status,
                extra={"store_id": store_id, "step": step.value},
            )
            raise EnqueueFailed


def get_step_enqueuer(settings: Settings) -> StepEnqueuer:
    """QStash when configured; a no-op in local/test; otherwise EnqueueFailed on use."""
    token = settings.QSTASH_TOKEN
    if token is not None and settings.PROVISIONING_BASE_URL:
        return QStashEnqueuer(
            token.get_secret_value(),
            settings.QSTASH_URL,
            settings.PROVISIONING_BASE_URL,
            retries=settings.PROVISIONING_STEP_RETRIES,
        )
    if settings.relaxed_environment:
        return NoopEnqueuer()
    return UnconfiguredEnqueuer()


async def mark_failed(provider: SessionProvider, store_id: str) -> bool:
    """PROVISIONING becomes FAILED. Any other status is left alone; True if changed."""
    async with provider.session() as session:
        result = await session.execute(
            update(Store)
            .where(Store.id == store_id, Store.status == StoreStatus.PROVISIONING)
            .values(status=StoreStatus.FAILED)
            .returning(Store.id)
        )
        changed = result.first() is not None
        await session.commit()
    if changed:
        logger.error("store provisioning failed", extra={"store_id": store_id})
    return changed


async def start_provisioning(
    provider: SessionProvider,
    enqueuer: StepEnqueuer,
    store_id: str,
    *,
    attempt: int = 0,
) -> bool:
    """Enqueue the first step. On failure the store is marked FAILED; returns success.

    ``attempt`` is 0 for the first run and the admin re-run number afterwards (KAN-200);
    it travels in every step's payload and dedup id.
    """
    try:
        await enqueuer.enqueue(store_id, Step.CREATE_DATABASE, attempt=attempt)
    except Exception as exc:  # noqa: BLE001 - the store is committed: never leave it stuck
        if not isinstance(exc, EnqueueFailed):
            logger.error(
                "provisioning enqueue crashed: %s",
                type(exc).__name__,
                extra={"store_id": store_id},
            )
        try:
            await mark_failed(provider, store_id)
        except Exception as failure:  # noqa: BLE001 - the store is committed: never 500 here
            logger.error(
                "marking store FAILED crashed: %s",
                type(failure).__name__,
                extra={"store_id": store_id},
            )
            report_exception(RuntimeError(f"mark_failed: {safe_reason(failure)}"))
        return False
    return True


async def _locked_provisioning_store(
    session: AsyncSession, store_id: str
) -> Store | None:
    """The store row under a lock, or None when it is not PROVISIONING (or missing)."""
    store = (
        await session.execute(
            select(Store).where(Store.id == store_id).with_for_update()
        )
    ).scalar_one_or_none()
    if store is None or store.status is not StoreStatus.PROVISIONING:
        return None
    return store


@dataclass(frozen=True)
class StepRunner:
    """Runs one step. Collaborators are injected so tests need no network or database."""

    provider: SessionProvider
    provisioner: Callable[[], DatabaseProvisioner]
    enqueuer: StepEnqueuer
    migrate: Callable[[str, SessionProvider], Awaitable[int]] = migrate_store

    async def run(self, step: Step, store_id: str, attempt: int = 0) -> None:
        """Run ``step`` then publish the next. Raises StepFailed to ask for a retry."""
        try:
            if not await self._is_provisioning(store_id):
                logger.info(
                    "provisioning step skipped: store not PROVISIONING",
                    extra={"store_id": store_id, "step": step.value},
                )
                return
            await self._execute(step, store_id)
        except (StepAbandoned, InvalidStoreId):
            await self.fail(store_id)
            return
        except StepFailed:
            raise
        except Exception as exc:  # noqa: BLE001 - any other failure is retried
            logger.error(
                "provisioning step failed: %s",
                type(exc).__name__,
                extra={"store_id": store_id, "step": step.value},
            )
            # Class name and SQLSTATE only: a driver or API error text can echo a DSN.
            report_exception(
                RuntimeError(f"provisioning step {step.value}: {safe_reason(exc)}")
            )
            raise StepFailed from None
        await self._advance(step, store_id, attempt)

    async def handle_step(self, raw_body: bytes) -> None:
        """Run the step a QStash delivery asks for. InvalidPayload or StepFailed on error."""
        parsed = parse_step_payload(_loads(raw_body))
        if parsed is None:
            raise InvalidPayload
        await self.run(*parsed)

    async def handle_exhausted(self, raw_body: bytes) -> None:
        """QStash gave up on a step (failure callback): the store becomes FAILED."""
        callback = _loads(raw_body)
        encoded = callback.get("sourceBody") if isinstance(callback, dict) else None
        if not isinstance(encoded, str):
            raise InvalidPayload
        try:
            source = _loads(base64.b64decode(encoded, validate=True))
        except (binascii.Error, ValueError):
            raise InvalidPayload from None
        parsed = parse_step_payload(source)
        if parsed is None:
            raise InvalidPayload
        await self.fail(parsed[1])

    async def fail(self, store_id: str) -> None:
        await mark_failed(self.provider, store_id)

    async def _is_provisioning(self, store_id: str) -> bool:
        async with self.provider.session() as session:
            status = (
                await session.execute(select(Store.status).where(Store.id == store_id))
            ).scalar_one_or_none()
        return status is StoreStatus.PROVISIONING

    async def _execute(self, step: Step, store_id: str) -> None:
        if step is Step.CREATE_DATABASE:
            await self._create_database(store_id)
        elif step is Step.RUN_MIGRATIONS:
            try:
                await self.migrate(store_id, self.provider)
            except StoreMigrationFailed:
                raise StepFailed from None
        else:
            await self._mark_ready(store_id)

    async def _create_database(self, store_id: str) -> None:
        database_name = database_name_for(store_id)
        # Outside any transaction: the provider call can be slow and is idempotent.
        connection_string = await self.provisioner().create_database(store_id)
        async with self.provider.session() as session:
            store = await _locked_provisioning_store(session, store_id)
            if store is None:
                return
            # Always replace: the call above rotated the store role's password.
            try:
                store_secrets.set_connection_string(store, connection_string)
            except (StoreSecretUnavailable, ValueError):
                raise StepAbandoned from None
            store.database_ref = database_name
            await session.commit()

    async def _mark_ready(self, store_id: str) -> None:
        async with self.provider.session() as session:
            store = await _locked_provisioning_store(session, store_id)
            if store is None:
                return
            if store.connection_string_encrypted is None or store.schema_version < 1:
                # Out of order delivery: retry, the earlier steps will have run.
                raise StepFailed
            store.status = StoreStatus.ACTIVE
            await session.commit()

    async def _advance(self, step: Step, store_id: str, attempt: int) -> None:
        following = NEXT_STEP[step]
        if following is None:
            return
        try:
            await self.enqueuer.enqueue(store_id, following, attempt=attempt)
        except EnqueueFailed:
            # This step is idempotent: retrying it re-publishes the next one.
            raise StepFailed from None


def _loads(raw: bytes | str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        raise InvalidPayload from None


def parse_step_payload(raw: Any) -> tuple[Step, str, int] | None:
    """(step, store_id, attempt) from a delivered body, or None when it is not valid.

    ``attempt`` is optional (a message published before KAN-200 has none: 0).
    """
    if not isinstance(raw, dict) or not {"store_id", "step"} <= set(raw) <= {
        "store_id",
        "step",
        "attempt",
    }:
        return None
    store_id, name, attempt = raw["store_id"], raw["step"], raw.get("attempt", 0)
    if not isinstance(store_id, str) or not isinstance(name, str):
        return None
    if type(attempt) is not int or not 0 <= attempt <= MAX_ATTEMPT:
        return None
    try:
        database_name_for(store_id)
        return Step(name), store_id, attempt
    except (InvalidStoreId, ValueError):
        return None
