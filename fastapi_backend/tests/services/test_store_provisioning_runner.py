"""``StepRunner`` error branches without a database (KAN-56).

The database-touching parts (`_is_provisioning`, `_execute`) are replaced; the real
branching of ``run`` (abandon, retry, log hygiene) and the payload handlers are tested.
"""

import base64
import json
import logging
from typing import Any

import pytest

from app.services import store_provisioning_job
from app.services.store_migrations import StoreVersionNotRecorded
from app.services.store_provisioning import InvalidStoreId
from app.services.store_provisioning_job import (
    EnqueueFailed,
    InvalidPayload,
    Step,
    StepAbandoned,
    StepFailed,
    StepRunner,
)

STORE_ID = "abcdefgh12345678abcdefgh"
DSN = "postgresql://owner:hunter2@ep-secret.neon.tech/store_x"


class Enqueuer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, Step]] = []

    async def enqueue(self, store_id: str, step: Step) -> None:
        if self.fail:
            raise EnqueueFailed
        self.calls.append((store_id, step))


class Runner(StepRunner):
    """Skips the database: the step either succeeds or raises ``error``."""

    def __init__(
        self,
        error: Exception | None = None,
        provisioning: bool = True,
        enqueuer: Enqueuer | None = None,
    ) -> None:
        super().__init__(
            provider=None,  # type: ignore[arg-type]
            provisioner=None,  # type: ignore[arg-type]
            enqueuer=enqueuer or Enqueuer(),
        )
        object.__setattr__(self, "_error", error)
        object.__setattr__(self, "_provisioning", provisioning)
        object.__setattr__(self, "failed", [])

    async def _is_provisioning(self, store_id: str) -> bool:
        return self._provisioning  # type: ignore[attr-defined,no-any-return]

    async def _execute(self, step: Step, store_id: str) -> None:
        if self._error:  # type: ignore[attr-defined]
            raise self._error  # type: ignore[attr-defined]

    async def fail(self, store_id: str) -> None:
        self.failed.append(store_id)  # type: ignore[attr-defined]


@pytest.mark.parametrize("error", [StepAbandoned(), InvalidStoreId("x")])
async def test_a_permanent_error_marks_the_store_failed_without_raising(error):
    runner = Runner(error=error)

    await runner.run(Step.CREATE_DATABASE, STORE_ID)

    assert runner.failed == [STORE_ID]  # type: ignore[attr-defined]
    assert runner.enqueuer.calls == []  # type: ignore[attr-defined]


async def test_a_store_version_not_recorded_error_is_retried():
    runner = Runner(error=StoreVersionNotRecorded(STORE_ID, "OperationalError"))

    with pytest.raises(StepFailed):
        await runner.run(Step.RUN_MIGRATIONS, STORE_ID)

    assert runner.failed == []  # type: ignore[attr-defined]


async def test_an_unexpected_error_is_retried_and_its_text_is_never_logged(
    caplog, monkeypatch
):
    reported: list[BaseException] = []
    monkeypatch.setattr(store_provisioning_job, "report_exception", reported.append)
    caplog.set_level(logging.DEBUG)
    runner = Runner(error=RuntimeError(f"cannot connect to {DSN}"))

    with pytest.raises(StepFailed) as raised:
        await runner.run(Step.CREATE_DATABASE, STORE_ID)

    assert raised.value.__cause__ is None
    assert "hunter2" not in caplog.text
    assert "ep-secret" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert len(reported) == 1
    assert "hunter2" not in str(reported[0])
    assert "ep-secret" not in str(reported[0])
    assert runner.failed == []  # type: ignore[attr-defined]


async def test_a_step_for_a_store_that_is_not_provisioning_does_nothing():
    runner = Runner(error=RuntimeError("must not run"), provisioning=False)

    await runner.run(Step.CREATE_DATABASE, STORE_ID)

    assert runner.failed == []  # type: ignore[attr-defined]
    assert runner.enqueuer.calls == []  # type: ignore[attr-defined]


async def test_a_successful_step_enqueues_the_next_one():
    runner = Runner()

    await runner.run(Step.CREATE_DATABASE, STORE_ID)
    await runner.run(Step.RUN_MIGRATIONS, STORE_ID)
    await runner.run(Step.MARK_READY, STORE_ID)

    assert runner.enqueuer.calls == [  # type: ignore[attr-defined]
        (STORE_ID, Step.RUN_MIGRATIONS),
        (STORE_ID, Step.MARK_READY),
    ]


async def test_a_failed_publish_of_the_next_step_is_retried():
    runner = Runner(enqueuer=Enqueuer(fail=True))

    with pytest.raises(StepFailed):
        await runner.run(Step.CREATE_DATABASE, STORE_ID)


def body(payload: Any) -> bytes:
    return json.dumps(payload).encode()


async def test_handle_step_runs_the_requested_step():
    ran: list[tuple[Step, str]] = []

    class Recording(Runner):
        async def run(self, step: Step, store_id: str) -> None:
            ran.append((step, store_id))

    await Recording().handle_step(
        body({"store_id": STORE_ID, "step": "run_migrations"})
    )

    assert ran == [(Step.RUN_MIGRATIONS, STORE_ID)]


@pytest.mark.parametrize("raw", [b"nope", b"[]", body({"store_id": STORE_ID})])
async def test_handle_step_rejects_a_bad_payload(raw):
    with pytest.raises(InvalidPayload):
        await Runner().handle_step(raw)


async def test_handle_exhausted_marks_the_source_store_failed():
    source = body({"store_id": STORE_ID, "step": "mark_ready"})
    runner = Runner()

    await runner.handle_exhausted(
        body({"status": 500, "sourceBody": base64.b64encode(source).decode()})
    )

    assert runner.failed == [STORE_ID]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "raw",
    [
        b"nope",
        body({}),
        body({"sourceBody": 5}),
        body({"sourceBody": "***"}),
        body({"sourceBody": base64.b64encode(b"nope").decode()}),
        body({"sourceBody": base64.b64encode(b"{}").decode()}),
    ],
)
async def test_handle_exhausted_rejects_a_bad_payload(raw):
    runner = Runner()

    with pytest.raises(InvalidPayload):
        await runner.handle_exhausted(raw)

    assert runner.failed == []  # type: ignore[attr-defined]
