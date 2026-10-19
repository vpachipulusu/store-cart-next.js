"""Test doubles for Stripe Connect (KAN-67): a recording Stripe client and an in-memory store."""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.core.stripe_billing import (
    StripeError,
    StripeForbidden,
    StripeNotFound,
    StripeRejected,
)
from app.core.stripe_connect import StripeAccountState
from app.models.platform.membership import MembershipRole
from app.repositories.connect_events import ConnectRoute
from app.repositories.org_connect import ConnectRecord

ACCOUNT_ID = "acct_new"


class FakeStripeConnect:
    """Implements StripeConnect; records every call and can be told to fail.

    Like Stripe, ``create_account`` returns the same account for the same idempotency key, and
    answers 409 (``StripeRejected``) while a request with that key is still in flight.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_on: str | None = None
        self.not_found_on_get = False
        self.forbidden_on_get = False
        self.reject_next_create = False
        self.account_state = StripeAccountState(False, False, False)
        self._accounts: dict[str, str] = {}
        self._in_flight: set[str] = set()

    def _record(self, call: str, /, **kwargs: Any) -> None:
        self.calls.append((call, kwargs))
        if self.fail_on in (call, "all"):
            raise StripeError("Stripe request failed")

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def last(self, name: str) -> dict[str, Any]:
        return next(args for call, args in reversed(self.calls) if call == name)

    async def get_account(self, account_id: str) -> StripeAccountState:
        self._record("get_account", account_id=account_id)
        # A real read yields, so concurrent deliveries interleave.
        await asyncio.sleep(0)
        if self.not_found_on_get:
            raise StripeNotFound("Stripe request failed")
        if self.forbidden_on_get:
            raise StripeForbidden("Stripe request failed")
        return self.account_state

    async def create_account(self, **kwargs: Any) -> str:
        self._record("create_account", **kwargs)
        key = kwargs["idempotency_key"]
        if self.reject_next_create or key in self._in_flight:
            self.reject_next_create = False
            raise StripeRejected("Stripe request failed")
        self._in_flight.add(key)
        try:
            await asyncio.sleep(0)
            return self._accounts.setdefault(key, ACCOUNT_ID)
        finally:
            self._in_flight.discard(key)

    async def create_account_link(self, **kwargs: Any) -> str:
        self._record("create_account_link", **kwargs)
        return "https://connect.stripe.test/setup/abc"


class FakeConnectStore:
    """Implements RoleLookup and ConnectStore in memory."""

    def __init__(self) -> None:
        self.roles: dict[tuple[str, str], MembershipRole] = {}
        self.orgs: dict[str, ConnectRecord] = {}
        self.event_at: dict[str, datetime] = {}
        # store id -> owning organisation id (KAN-69 routing)
        self.stores: dict[str, str] = {}

    def add(self, record: ConnectRecord, user_id: str, role: MembershipRole) -> None:
        self.orgs[record.id] = record
        self.roles[(record.id, user_id)] = role

    async def get_role(
        self, organization_id: str, user_id: str
    ) -> MembershipRole | None:
        return self.roles.get((organization_id, user_id))

    async def get(self, organization_id: str) -> ConnectRecord | None:
        return self.orgs.get(organization_id)

    async def organization_for_account(self, account_id: str) -> str | None:
        return next(
            (
                r.id
                for r in self.orgs.values()
                if r.stripe_connect_account_id == account_id
            ),
            None,
        )

    async def store_belongs_to(self, store_id: str, organization_id: str) -> bool:
        return self.stores.get(store_id) == organization_id

    async def link_account(self, organization_id: str, account_id: str) -> str:
        record = self.orgs[organization_id]
        if record.stripe_connect_account_id is None:
            record = replace(record, stripe_connect_account_id=account_id)
            self.orgs[organization_id] = record
        return record.stripe_connect_account_id or account_id

    async def apply_account_update(
        self,
        account_id: str,
        *,
        charges_enabled: bool,
        payouts_enabled: bool,
        details_submitted: bool,
        event_at: datetime,
    ) -> bool:
        for key, record in self.orgs.items():
            if record.stripe_connect_account_id != account_id:
                continue
            last = self.event_at.get(key)
            if last is not None and last > event_at:
                return False
            self.event_at[key] = event_at
            self.orgs[key] = replace(
                record,
                connect_charges_enabled=charges_enabled,
                connect_payouts_enabled=payouts_enabled,
                connect_details_submitted=details_submitted,
            )
            return True
        return False


@dataclass(frozen=True)
class ClaimedEvent:
    stripe_event_id: str
    type: str
    route: ConnectRoute
    created: datetime


class FakeConnectEvents:
    """Implements ConnectEventLog: like the unique index, a second claim of an id loses.

    Claims are pending until the session commits; ``pending`` is dropped on rollback, so a
    failed handler leaves the event unrecorded, as the real transaction would.
    """

    def __init__(self) -> None:
        self.recorded: dict[str, ClaimedEvent] = {}
        self.pending: dict[str, ClaimedEvent] = {}

    async def is_recorded(self, stripe_event_id: str) -> bool:
        return stripe_event_id in self.recorded

    async def claim(
        self,
        stripe_event_id: str,
        event_type: str,
        route: ConnectRoute,
        created: datetime,
    ) -> bool:
        if stripe_event_id in self.recorded or stripe_event_id in self.pending:
            return False
        self.pending[stripe_event_id] = ClaimedEvent(
            stripe_event_id, event_type, route, created
        )
        return True

    def commit(self) -> None:
        self.recorded.update(self.pending)
        self.pending.clear()

    def rollback(self) -> None:
        self.pending.clear()


class FakeEventSession:
    """A session whose commit and rollback settle the fake event log's pending claims."""

    def __init__(self, events: FakeConnectEvents) -> None:
        self.events = events
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        self.events.commit()

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.events.rollback()


def connect_record(**overrides: Any) -> ConnectRecord:
    base = ConnectRecord(
        id="org1",
        stripe_connect_account_id=None,
        connect_charges_enabled=False,
        connect_payouts_enabled=False,
        connect_details_submitted=False,
    )
    return replace(base, **overrides)
