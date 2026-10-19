"""Stripe Connect onboarding per organisation (KAN-67).

``start_onboarding`` creates the organisation's Express connected account on first use,
then returns a Stripe-hosted onboarding link. ``status`` reads the capability flags that
the Connect webhook (``ConnectWebhookService``) keeps in sync with Stripe.

Both require the OWNER or ADMIN role (the same check as billing); a non-member sees
"not found". Nothing here writes capability flags except the webhook: returning from
onboarding does not enable charges, Stripe's event does.

Checkout guard (AC3): this module only provides ``require_charges_enabled`` and
``require_org_charges_enabled``. The checkout story (KAN-68) must call one of them before it
creates a payment for an organisation's store, and map ``ChargesNotEnabled`` to an HTTP 409
with a generic message.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.stripe_billing import (
    StripeError,
    StripeForbidden,
    StripeNotFound,
    StripeRejected,
)
from app.core.stripe_connect import StripeAccountState, StripeConnect
from app.models.platform.membership import MembershipRole
from app.repositories.connect_events import ConnectRoute
from app.repositories.org_connect import ConnectRecord
from app.services.org_billing import (
    BILLING_ROLES,
    BillingForbidden,
    BillingUnavailable,
    OrganizationNotFound,
    validate_return_url,
)

logger = logging.getLogger(__name__)

UPDATED_EVENT_TYPE = "account.updated"
DEAUTHORIZED_EVENT_TYPE = "account.application.deauthorized"
ACCOUNT_EVENT_TYPES = frozenset({UPDATED_EVENT_TYPE, DEAUTHORIZED_EVENT_TYPE})
ACCOUNT_CREATE_ATTEMPTS = 2
ACCOUNT_RETRY_DELAY_SECONDS = 0.2
ACCOUNT_ID_PATTERN = re.compile(r"acct_[A-Za-z0-9]+")
EVENT_ID_PATTERN = re.compile(r"evt_[A-Za-z0-9]+")
# Platform ids: cuid2 now, Prisma cuid for copied rows.
STORE_ID_PATTERN = re.compile(r"[A-Za-z0-9]{1,64}")
# Stripe event types are lowercase dotted names; anything else is not logged verbatim.
EVENT_TYPE_TOKEN = re.compile(r"[a-z0-9_.]{1,64}")
NO_ACCESS = StripeAccountState(
    charges_enabled=False, payouts_enabled=False, details_submitted=False
)


class ChargesNotEnabled(Exception):
    """The organisation cannot take payments yet: no account, or charges not enabled."""


class MalformedConnectEvent(Exception):
    """The event is signed but lacks the account id the handler needs (400)."""


class WebhookOutcome(StrEnum):
    PROCESSED = "processed"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"


# A store-scoped event handler: runs inside the transaction that records the event.
StoreEventHandler = Callable[[ConnectRoute, Mapping[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ConnectStatus:
    has_account: bool
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool


class ConnectStore(Protocol):
    async def get(self, organization_id: str) -> ConnectRecord | None: ...

    async def organization_for_account(self, account_id: str) -> str | None: ...

    async def store_belongs_to(self, store_id: str, organization_id: str) -> bool: ...

    async def link_account(self, organization_id: str, account_id: str) -> str: ...

    async def apply_account_update(
        self,
        account_id: str,
        *,
        charges_enabled: bool,
        payouts_enabled: bool,
        details_submitted: bool,
        event_at: datetime,
    ) -> bool: ...


class ConnectEventLog(Protocol):
    async def is_recorded(self, stripe_event_id: str) -> bool: ...

    async def claim(
        self,
        stripe_event_id: str,
        event_type: str,
        route: ConnectRoute,
        created: datetime,
    ) -> bool: ...


class RoleLookup(Protocol):
    async def get_role(
        self, organization_id: str, user_id: str
    ) -> MembershipRole | None: ...


def require_charges_enabled(record: ConnectRecord) -> None:
    """Raise ``ChargesNotEnabled`` unless the organisation has an account with charges on."""
    if record.stripe_connect_account_id is None or not record.connect_charges_enabled:
        raise ChargesNotEnabled


async def require_org_charges_enabled(
    store: ConnectStore, organization_id: str
) -> None:
    """The same guard, loading the organisation first (an unknown organisation also blocks)."""
    record = await store.get(organization_id)
    if record is None:
        raise ChargesNotEnabled
    require_charges_enabled(record)


class ConnectService:
    def __init__(
        self,
        roles: RoleLookup,
        store: ConnectStore,
        session: AsyncSession,
        stripe: StripeConnect,
        origins: frozenset[str],
    ) -> None:
        self._roles = roles
        self._store = store
        self._session = session
        self._stripe = stripe
        self._origins = origins

    async def _authorize(self, organization_id: str, user_id: str) -> ConnectRecord:
        role = await self._roles.get_role(organization_id, user_id)
        if role is None:
            raise OrganizationNotFound
        if role not in BILLING_ROLES:
            raise BillingForbidden
        record = await self._store.get(organization_id)
        if record is None:
            raise OrganizationNotFound
        # End the read transaction so no connection is held while Stripe is called.
        await self._session.rollback()
        return record

    async def status(self, organization_id: str, user_id: str) -> ConnectStatus:
        record = await self._authorize(organization_id, user_id)
        return ConnectStatus(
            has_account=record.stripe_connect_account_id is not None,
            charges_enabled=record.connect_charges_enabled,
            payouts_enabled=record.connect_payouts_enabled,
            details_submitted=record.connect_details_submitted,
        )

    async def start_onboarding(
        self,
        organization_id: str,
        user_id: str,
        *,
        return_url: str,
        refresh_url: str,
    ) -> str:
        record = await self._authorize(organization_id, user_id)
        return_target = validate_return_url(return_url, self._origins)
        refresh_target = validate_return_url(refresh_url, self._origins)
        account_id = record.stripe_connect_account_id or await self._create_account(
            record.id
        )
        try:
            # Links are single use and expire in minutes: always a fresh server-side key.
            return await self._stripe.create_account_link(
                account_id=account_id,
                refresh_url=refresh_target,
                return_url=return_target,
                idempotency_key=f"sc-connect-link-{record.id}-{new_id()}",
            )
        except StripeError:
            raise BillingUnavailable from None

    async def _create_account(self, organization_id: str) -> str:
        created = await self._create_account_at_stripe(organization_id)
        try:
            saved = await self._store.link_account(organization_id, created)
        except LookupError:
            # The organisation was deleted between the read and the link.
            await self._session.rollback()
            raise OrganizationNotFound from None
        await self._session.commit()
        return saved

    async def _create_account_at_stripe(self, organization_id: str) -> str:
        # Deterministic key: a retry gets the same account back while Stripe remembers it (about 24 hours).
        key = f"sc-connect-account-{organization_id}"
        for attempt in range(ACCOUNT_CREATE_ATTEMPTS):
            try:
                return await self._stripe.create_account(
                    organization_id=organization_id, idempotency_key=key
                )
            except StripeRejected:
                # Stripe answers 409 while a request with the same key is still in flight: a racing
                # first request for this organisation. Use the account it linked, or try again.
                linked = await self._linked_account(organization_id)
                if linked is not None:
                    return linked
                if attempt == ACCOUNT_CREATE_ATTEMPTS - 1:
                    raise BillingUnavailable from None
                await asyncio.sleep(ACCOUNT_RETRY_DELAY_SECONDS)
            except StripeError:
                raise BillingUnavailable from None
        raise BillingUnavailable

    async def _linked_account(self, organization_id: str) -> str | None:
        record = await self._store.get(organization_id)
        await self._session.rollback()
        return None if record is None else record.stripe_connect_account_id


class ConnectWebhookService:
    """Routes each Connect event to its organisation (and store) and applies it at most once (KAN-67, KAN-69).

    Routing: the event's connected account picks the organisation (the account id is unique per
    organisation and is set by Stripe, not by the payload's sender). Store-scoped events
    (``store_handlers``, registered by the payment stories) also need ``metadata.store_id`` on
    their object, and that store must belong to the same organisation. An event for an unknown
    account or store is acknowledged, logged and not recorded, so it never makes Stripe retry.

    At most once: the event id is claimed in ``ConnectEventLog`` in the same transaction as the
    side effect, then committed. A failed handler rolls both back, so Stripe's retry runs it
    again; a concurrent delivery of the same id waits on the unique index and then sees a
    duplicate. A cheap pre-check skips duplicates before any Stripe call.

    ``account.updated`` is only a trigger: Stripe delivers events unordered and ``created`` has
    one-second resolution, so the flags are never taken from the payload. The account is read
    from Stripe outside any transaction and stored stamped with the time the read started, so a
    slower, older read that finishes later cannot overwrite a newer one.
    ``account.application.deauthorized`` clears the flags. Other events are acknowledged and ignored.
    """

    def __init__(
        self,
        store: ConnectStore,
        events: ConnectEventLog,
        session: AsyncSession,
        stripe: Callable[[], StripeConnect],
        *,
        store_handlers: Mapping[str, StoreEventHandler] | None = None,
    ) -> None:
        self._store = store
        self._events = events
        self._session = session
        # A factory, so an unset STRIPE_SECRET_KEY only matters once an event needs Stripe.
        self._stripe = stripe
        handlers = dict(store_handlers or {})
        if ACCOUNT_EVENT_TYPES & handlers.keys():
            raise ValueError("account events are not store-scoped")
        self._store_handlers = handlers

    async def handle(self, event: Mapping[str, Any]) -> WebhookOutcome:
        """Apply one verified event; raises MalformedConnectEvent or the handler's own error."""
        event_type = event.get("type")
        if not isinstance(event_type, str) or not self._handles(event_type):
            logger.info("connect event ignored: type=%s", _loggable_type(event_type))
            return WebhookOutcome.IGNORED
        event_id = _event_id(event.get("id"))
        created = _created(event.get("created"))
        account_id = _event_account_id(event_type, event)
        try:
            return await self._process(event_id, event_type, created, account_id, event)
        except BaseException:
            await self._session.rollback()
            raise

    def _handles(self, event_type: str) -> bool:
        return event_type in ACCOUNT_EVENT_TYPES or event_type in self._store_handlers

    async def _process(
        self,
        event_id: str,
        event_type: str,
        created: datetime,
        account_id: str,
        event: Mapping[str, Any],
    ) -> WebhookOutcome:
        route = await self._route(event_type, account_id, event)
        recorded = route is not None and await self._events.is_recorded(event_id)
        # End the read transaction so no connection is held while Stripe is called.
        await self._session.rollback()
        if route is None:
            return WebhookOutcome.IGNORED
        if recorded:
            logger.info("connect event already processed", extra={"event_id": event_id})
            return WebhookOutcome.DUPLICATE
        effect = await self._prepare(event_type, route, event)
        if not await self._events.claim(event_id, event_type, route, created):
            await self._session.rollback()
            logger.info("connect event already processed", extra={"event_id": event_id})
            return WebhookOutcome.DUPLICATE
        await effect()
        await self._session.commit()
        return WebhookOutcome.PROCESSED

    async def _route(
        self, event_type: str, account_id: str, event: Mapping[str, Any]
    ) -> ConnectRoute | None:
        organization_id = await self._store.organization_for_account(account_id)
        if organization_id is None:
            # A signed event for an account we never linked costs no Stripe call.
            logger.info("connect webhook for an unknown account")
            return None
        if event_type not in self._store_handlers:
            return ConnectRoute(organization_id, account_id, None)
        store_id = _metadata_store_id(event)
        if store_id is None:
            logger.info("connect store event without a store id: type=%s", event_type)
            return None
        if not await self._store.store_belongs_to(store_id, organization_id):
            logger.warning(
                "connect store event names a store outside the account's organisation",
                extra={"organization_id": organization_id},
            )
            return None
        return ConnectRoute(organization_id, account_id, store_id)

    async def _prepare(
        self, event_type: str, route: ConnectRoute, event: Mapping[str, Any]
    ) -> Callable[[], Awaitable[None]]:
        """Do any Stripe read first; return the side effect to run inside the claim's transaction."""
        if event_type == UPDATED_EVENT_TYPE:
            observed_at = datetime.now(UTC)
            state = await self._read_account(route.account_id)
            return lambda: self._apply(route.account_id, state, observed_at)
        if event_type == DEAUTHORIZED_EVENT_TYPE:
            observed_at = datetime.now(UTC)
            return lambda: self._apply(route.account_id, NO_ACCESS, observed_at)
        handler = self._store_handlers[event_type]
        obj = _event_object(event)
        return lambda: handler(route, obj)

    async def _read_account(self, account_id: str) -> StripeAccountState:
        try:
            return await self._stripe().get_account(account_id)
        except (StripeNotFound, StripeForbidden):
            # Gone, or the account revoked the platform (403): nothing to read, so no access.
            return NO_ACCESS

    async def _apply(
        self, account_id: str, state: StripeAccountState, observed_at: datetime
    ) -> None:
        updated = await self._store.apply_account_update(
            account_id,
            charges_enabled=state.charges_enabled,
            payouts_enabled=state.payouts_enabled,
            details_submitted=state.details_submitted,
            event_at=observed_at,
        )
        if not updated:
            # Unlinked since routing, or a newer read already stored: nothing to retry.
            logger.info("connect webhook changed no organisation")


def _account_id(value: Any) -> str:
    if not isinstance(value, str) or not ACCOUNT_ID_PATTERN.fullmatch(value):
        raise MalformedConnectEvent
    return value


def _event_id(value: Any) -> str:
    if not isinstance(value, str) or not EVENT_ID_PATTERN.fullmatch(value):
        raise MalformedConnectEvent
    return value


def _created(value: Any) -> datetime:
    # bool is an int subclass; Stripe sends a positive Unix time.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MalformedConnectEvent
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        raise MalformedConnectEvent from None


def _event_object(event: Mapping[str, Any]) -> Mapping[str, Any]:
    data = event.get("data")
    obj = data.get("object") if isinstance(data, Mapping) else None
    if not isinstance(obj, Mapping):
        raise MalformedConnectEvent
    return obj


def _event_account_id(event_type: str, event: Mapping[str, Any]) -> str:
    """The connected account the event belongs to.

    Events from connected accounts carry it as the event's ``account``. ``account.updated``
    also names it as its object; when both are present they must agree.
    """
    if event_type != UPDATED_EVENT_TYPE:
        # For deauthorization the object is the application, not the account.
        return _account_id(event.get("account"))
    account_id = _account_id(_event_object(event).get("id"))
    declared = event.get("account")
    if declared is not None and _account_id(declared) != account_id:
        raise MalformedConnectEvent
    return account_id


def _metadata_store_id(event: Mapping[str, Any]) -> str | None:
    metadata = _event_object(event).get("metadata")
    store_id = metadata.get("store_id") if isinstance(metadata, Mapping) else None
    if not isinstance(store_id, str) or not STORE_ID_PATTERN.fullmatch(store_id):
        return None
    return store_id


def _loggable_type(event_type: Any) -> str:
    if isinstance(event_type, str) and EVENT_TYPE_TOKEN.fullmatch(event_type):
        return event_type
    return "unlisted"
