"""Drives the store provisioning chain inline for local e2e (KAN-73).

QStash is not available on a developer machine, so a new store stays PROVISIONING and the product API
(which needs an ACTIVE store for writes) rejects it. This runs the three real steps in order against the
backend's own platform database: create_database, run_migrations, mark_ready. It is not part of the app.

Usage (from fastapi_backend/, with the same environment as uvicorn):
    PYTHONPATH=. uv run python <this file> <store_id>
"""

import asyncio
import sys

from app.core.config import settings
from app.core.database import DefaultSessionProvider, async_session_maker
from app.services.store_provisioning import get_database_provisioner
from app.services.store_provisioning_job import Step, StepRunner


class InlineEnqueuer:
    """Collects the next step the runner asks for, so this script can run it itself."""

    def __init__(self) -> None:
        self.pending: list[Step] = []

    async def enqueue(self, store_id: str, step: Step, *, attempt: int) -> None:
        self.pending.append(step)


async def main(store_id: str) -> None:
    enqueuer = InlineEnqueuer()
    runner = StepRunner(
        provider=DefaultSessionProvider(async_session_maker),
        provisioner=lambda: get_database_provisioner(settings),
        enqueuer=enqueuer,
    )
    await runner.run(Step.CREATE_DATABASE, store_id)
    while enqueuer.pending:
        await runner.run(enqueuer.pending.pop(0), store_id)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: activate_store.py <store_id>")
    asyncio.run(main(sys.argv[1]))
