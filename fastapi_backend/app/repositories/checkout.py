"""Platform read for a storefront checkout (KAN-68). No business rules.

One query: the ACTIVE store with a slug, joined to its organisation's Stripe Connect state
and ``platform_fee_bps``. Like the storefront lookup, the status filter is an allowlist.
"""

from dataclasses import dataclass

from sqlalchemy import select

from app.models.platform.organization import Organization
from app.models.platform.store import Store, StoreStatus
from app.repositories.base import BaseRepository
from app.repositories.org_connect import ConnectRecord


@dataclass(frozen=True)
class CheckoutStoreRow:
    store_id: str
    slug: str
    connect: ConnectRecord
    platform_fee_bps: int


class CheckoutRepository(BaseRepository):
    async def find_active_store(self, slug: str) -> CheckoutStoreRow | None:
        row = (
            await self._session.execute(
                select(
                    Store.id,
                    Store.slug,
                    Organization.id.label("organization_id"),
                    Organization.stripe_connect_account_id,
                    Organization.connect_charges_enabled,
                    Organization.connect_payouts_enabled,
                    Organization.connect_details_submitted,
                    Organization.platform_fee_bps,
                )
                .join(Organization, Organization.id == Store.organization_id)
                .where(Store.slug == slug, Store.status == StoreStatus.ACTIVE)
            )
        ).one_or_none()
        if row is None:
            return None
        return CheckoutStoreRow(
            store_id=str(row.id),
            slug=str(row.slug),
            connect=ConnectRecord(
                id=row.organization_id,
                stripe_connect_account_id=row.stripe_connect_account_id,
                connect_charges_enabled=row.connect_charges_enabled,
                connect_payouts_enabled=row.connect_payouts_enabled,
                connect_details_submitted=row.connect_details_submitted,
            ),
            platform_fee_bps=int(row.platform_fee_bps),
        )
