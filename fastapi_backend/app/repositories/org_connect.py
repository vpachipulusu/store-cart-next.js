from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, update

from app.models.platform.organization import Organization
from app.models.platform.store import Store
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class ConnectRecord:
    """An organisation's Stripe Connect state."""

    id: str
    stripe_connect_account_id: str | None
    connect_charges_enabled: bool
    connect_payouts_enabled: bool
    connect_details_submitted: bool


class OrgConnectRepository(BaseRepository):
    async def get(self, organization_id: str) -> ConnectRecord | None:
        row = (
            await self._session.execute(
                select(
                    Organization.id,
                    Organization.stripe_connect_account_id,
                    Organization.connect_charges_enabled,
                    Organization.connect_payouts_enabled,
                    Organization.connect_details_submitted,
                ).where(Organization.id == organization_id)
            )
        ).one_or_none()
        return None if row is None else ConnectRecord(*row)

    async def organization_for_account(self, account_id: str) -> str | None:
        """The organisation linked to a connected account (the column is unique)."""
        return (
            await self._session.execute(
                select(Organization.id).where(
                    Organization.stripe_connect_account_id == account_id
                )
            )
        ).scalar_one_or_none()

    async def store_belongs_to(self, store_id: str, organization_id: str) -> bool:
        return (
            await self._session.execute(
                select(Store.id)
                .where(Store.id == store_id, Store.organization_id == organization_id)
                .limit(1)
            )
        ).first() is not None

    async def link_account(self, organization_id: str, account_id: str) -> str:
        """Save the connected account id if none is saved yet; return the id now saved.

        The conditional update keeps the first link when two requests race, so one
        organisation never ends up with two accounts.
        """
        await self._session.execute(
            update(Organization)
            .where(
                Organization.id == organization_id,
                Organization.stripe_connect_account_id.is_(None),
            )
            .values(stripe_connect_account_id=account_id)
        )
        saved = (
            await self._session.execute(
                select(Organization.stripe_connect_account_id).where(
                    Organization.id == organization_id
                )
            )
        ).scalar_one()
        if saved is None:
            raise LookupError("organization has no Stripe Connect account")
        return saved

    async def apply_account_update(
        self,
        account_id: str,
        *,
        charges_enabled: bool,
        payouts_enabled: bool,
        details_submitted: bool,
        event_at: datetime,
    ) -> bool:
        """Store the flags Stripe reported at ``event_at``; True if an organisation was updated.

        ``event_at`` is when the state was read from Stripe. One atomic statement, so a read that
        started earlier than the stored one changes nothing, and a repeat rewrites the same values.
        """
        result = await self._session.execute(
            update(Organization)
            .where(
                Organization.stripe_connect_account_id == account_id,
                or_(
                    Organization.stripe_connect_event_at.is_(None),
                    Organization.stripe_connect_event_at <= event_at,
                ),
            )
            .values(
                connect_charges_enabled=charges_enabled,
                connect_payouts_enabled=payouts_enabled,
                connect_details_submitted=details_submitted,
                stripe_connect_event_at=event_at,
            )
        )
        return bool(getattr(result, "rowcount", 0))
