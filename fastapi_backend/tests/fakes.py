"""Test doubles for the database session seam (no real database needed)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.exc import OperationalError

from app.core.database import SessionProvider


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value


class FakeSession:
    """Stands in for AsyncSession: records statements, returns a canned value."""

    def __init__(self, value: Any = 1, error: Exception | None = None) -> None:
        self.statements: list[str] = []
        self._value = value
        self._error = error

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(str(statement))
        if self._error is not None:
            raise self._error
        return FakeResult(self._value)


class FakeSessionProvider:
    """Implements the SessionProvider protocol around a FakeSession."""

    def __init__(self, session: FakeSession) -> None:
        self.fake_session = session
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        self.opened += 1
        try:
            yield self.fake_session
        finally:
            self.closed += 1


def failing_session() -> FakeSession:
    return FakeSession(error=OperationalError("SELECT 1", {}, Exception("down")))


def as_provider(provider: FakeSessionProvider) -> SessionProvider:
    """Static proof that the fake satisfies the protocol (checked by mypy)."""
    return provider
