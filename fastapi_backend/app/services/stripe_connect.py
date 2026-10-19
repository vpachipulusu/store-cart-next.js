"""Stripe Connect onboarding per organisation (KAN-67).

``start_onboarding`` creates the organisation's Express connected account on first use,
then returns a Stripe-hosted onboarding link. ``status`` reads the capability flags that
the Connect webhook (``ConnectWebhookService``) keeps in sync from ``account.updated``.

Both require the OWNER or ADMIN role (the same check as billing); a non-member sees
"not found". Nothing here writes capability flags except the webhook: returning from
onboarding does not enable charges, Stripe's event does.

Checkout guard (AC3): checkout code must call ``require_charges_enabled`` (or
``require_org_charges_enabled``) before it creates a payment for an organisation's
store, and map ``ChargesNotEnabled`` to an HTTP 409 with a generic message.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.stripe_billing import StripeError
from app.core.stripe_connect import StripeConnect
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

HANDLED_EVENT_TYPE = "account.updated"


class ChargesNotEnabled(Exception):
    """The organisation cannot take payments yet: no account, or charges not enabled."""


class MalformedConnectEvent(Exception):
    """The event is signed but not shaped like an ``account.updated`` event (400)."""


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
        request_key: str | None,
    ) -> str:
        record = await self._authorize(organization_id, user_id)
        return_target = validate_return_url(return_url, self._origins)
        refresh_target = validate_return_url(refresh_url, self._origins)
        account_id = record.stripe_connect_account_id or await self._create_account(
            record.id
        )
        try:
            return await self._stripe.create_account_link(
                account_id=account_id,
                refresh_url=refresh_target,
                return_url=return_target,
                idempotency_key=f"sc-connect-link-{record.id}-{request_key or new_id()}",
            )
        except StripeError:
            raise BillingUnavailable from None

    async def _create_account(self, organization_id: str) -> str:
        try:
            # Deterministic key: a retry after a failed save gets the same account back.
            created = await self._stripe.create_account(
                organization_id=organization_id,
                idempotency_key=f"sc-connect-account-{organization_id}",
            )
        except StripeError:
            raise BillingUnavailable from None
        try:
            saved = await self._store.link_account(organization_id, created)
        except LookupError:
            # The organisation was deleted between the read and the link.
            await self._session.rollback()
            raise OrganizationNotFound from None
        await self._session.commit()
        return saved


def _flag(account: dict[str, Any], name: str) -> bool:
    value = account.get(name)
    if not isinstance(value, bool):
        raise MalformedConnectEvent
    return value


class ConnectWebhookService:
    """Applies ``account.updated``; every other event type is acknowledged and ignored."""

    def __init__(self, store: ConnectStore, session: AsyncSession) -> None:
        self._store = store
        self._session = session

    async def handle(self, event: dict[str, Any]) -> WebhookOutcome:
        if event.get("type") != HANDLED_EVENT_TYPE:
            return WebhookOutcome.IGNORED
        data = event.get("data")
        account = data.get("object") if isinstance(data, dict) else None
        created = event.get("created")
        if not isinstance(account, dict) or isinstance(created, bool):
            raise MalformedConnectEvent
        if not isinstance(created, int):
            raise MalformedConnectEvent
        account_id = account.get("id")
        if not isinstance(account_id, str) or not account_id:
            raise MalformedConnectEvent
        updated = await self._store.apply_account_update(
            account_id,
            charges_enabled=_flag(account, "charges_enabled"),
            payouts_enabled=_flag(account, "payouts_enabled"),
            details_submitted=_flag(account, "details_submitted"),
            event_at=datetime.fromtimestamp(created, UTC),
        )
        await self._session.commit()
        if not updated:
            # Unknown account, or an older event than the one applied: nothing to retry.
            logger.info("connect account.updated changed no organisation")
            return WebhookOutcome.IGNORED
        return WebhookOutcome.PROCESSED
