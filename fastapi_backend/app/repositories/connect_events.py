"""The Stripe Connect event ledger (KAN-69): one row per applied event, keyed on its id."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.ids import new_id
from app.models.platform.stripe_connect_event import StripeConnectEvent
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class ConnectRoute:
    """Where a Connect event belongs: the organisation that owns the connected account,
    and for store-scoped events the store named in the object's metadata."""

    organization_id: str
    account_id: str
    store_id: str | None


class ConnectEventRepository(BaseRepository):
    async def is_recorded(self, stripe_event_id: str) -> bool:
        """A cheap pre-check before calling Stripe; ``claim`` is what decides."""
        return (
            await self._session.execute(
                select(StripeConnectEvent.id)
                .where(StripeConnectEvent.stripe_event_id == stripe_event_id)
                .limit(1)
            )
        ).first() is not None

    async def claim(
        self,
        stripe_event_id: str,
        event_type: str,
        route: ConnectRoute,
        created: datetime,
    ) -> bool:
        """Insert the event id in the caller's transaction; False if already recorded.

        A concurrent delivery of the same id blocks on the unique index until the first
        transaction ends: it then sees a duplicate after a commit, or inserts itself after
        a rollback.
        """
        statement = (
            pg_insert(StripeConnectEvent)
            .values(
                id=new_id(),
                stripe_event_id=stripe_event_id,
                type=event_type,
                stripe_account_id=route.account_id,
                organization_id=route.organization_id,
                store_id=route.store_id,
                stripe_created_at=created,
            )
            .on_conflict_do_nothing(index_elements=[StripeConnectEvent.stripe_event_id])
            .returning(StripeConnectEvent.id)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None
