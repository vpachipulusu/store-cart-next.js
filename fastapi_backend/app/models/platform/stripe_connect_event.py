from datetime import datetime

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import CreatedAtMixin, IdMixin


class StripeConnectEvent(IdMixin, CreatedAtMixin, Base):
    """One row per Stripe Connect event that was processed (KAN-69).

    The Connect counterpart of ``stripe_events``: a separate endpoint, secret and ledger.
    Processed includes a no-op (a newer read already stored). The unique ``stripe_event_id`` is the idempotency key, inserted in the same transaction
    as the event's side effect, so a rolled-back handler leaves no row and Stripe's retry runs
    it again. ``organization_id`` and ``store_id`` record where the event was routed. Rows hold
    no payload.
    """

    __tablename__ = "stripe_connect_events"
    __table_args__ = (
        Index(
            "ix_stripe_connect_events_store_id",
            "store_id",
            postgresql_where=text("store_id IS NOT NULL"),
        ),
    )

    stripe_event_id: Mapped[str] = mapped_column(unique=True)
    type: Mapped[str]
    stripe_account_id: Mapped[str]
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Mostly null (account events), so the index behind the SET NULL cascade is partial.
    store_id: Mapped[str | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL")
    )
    stripe_created_at: Mapped[datetime]
