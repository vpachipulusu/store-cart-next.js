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
from collections.abc import Callable
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
ACCOUNT_CREATE_ATTEMPTS = 2
ACCOUNT_RETRY_DELAY_SECONDS = 0.2
ACCOUNT_ID_PATTERN = re.compile(r"acct_[A-Za-z0-9]+")
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


@dataclass(frozen=True)
class ConnectStatus:
    has_account: bool
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool


class ConnectStore(Protocol):
    async def get(self, organization_id: str) -> ConnectRecord | None: ...

    async def account_exists(self, account_id: str) -> bool: ...

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
    """Keeps the flags in step with Stripe from ``account.updated`` and ``account.application.deauthorized``.

    The event is only a trigger: Stripe delivers events unordered and ``created`` has one-second
    resolution, so the flags are never taken from the payload. ``account.updated`` retrieves the
    account and stores what Stripe reports now; the row is stamped with the time the read started,
    so a slower, older read that finishes later cannot overwrite a newer one.
    ``account.application.deauthorized`` clears the flags. Other events are acknowledged and ignored.
    """

    def __init__(
        self,
        store: ConnectStore,
        session: AsyncSession,
        stripe: Callable[[], StripeConnect],
    ) -> None:
        self._store = store
        self._session = session
        # A factory, so an unset STRIPE_SECRET_KEY only matters once an event needs Stripe.
        self._stripe = stripe

    async def handle(self, event: dict[str, Any]) -> WebhookOutcome:
        event_type = event.get("type")
        if event_type == UPDATED_EVENT_TYPE:
            return await self._sync(_updated_account_id(event))
        if event_type == DEAUTHORIZED_EVENT_TYPE:
            return await self._apply(
                _deauthorized_account_id(event), NO_ACCESS, datetime.now(UTC)
            )
        return WebhookOutcome.IGNORED

    async def _sync(self, account_id: str) -> WebhookOutcome:
        # A signed event for an account we never linked costs no Stripe call.
        if not await self._store.account_exists(account_id):
            await self._session.rollback()
            logger.info("connect webhook for an unknown account")
            return WebhookOutcome.IGNORED
        observed_at = datetime.now(UTC)
        try:
            state = await self._stripe().get_account(account_id)
        except (StripeNotFound, StripeForbidden):
            # Gone, or the account revoked the platform (403): nothing to read, so no access.
            state = NO_ACCESS
        return await self._apply(account_id, state, observed_at)

    async def _apply(
        self, account_id: str, state: StripeAccountState, observed_at: datetime
    ) -> WebhookOutcome:
        updated = await self._store.apply_account_update(
            account_id,
            charges_enabled=state.charges_enabled,
            payouts_enabled=state.payouts_enabled,
            details_submitted=state.details_submitted,
            event_at=observed_at,
        )
        await self._session.commit()
        if not updated:
            # Unknown account, or a newer read already stored: nothing to retry.
            logger.info("connect webhook changed no organisation")
            return WebhookOutcome.IGNORED
        return WebhookOutcome.PROCESSED


def _account_id(value: Any) -> str:
    if not isinstance(value, str) or not ACCOUNT_ID_PATTERN.fullmatch(value):
        raise MalformedConnectEvent
    return value


def _updated_account_id(event: dict[str, Any]) -> str:
    data = event.get("data")
    account = data.get("object") if isinstance(data, dict) else None
    if not isinstance(account, dict):
        raise MalformedConnectEvent
    return _account_id(account.get("id"))


def _deauthorized_account_id(event: dict[str, Any]) -> str:
    # The event's object is the application; the connected account is the event's `account`.
    return _account_id(event.get("account"))
