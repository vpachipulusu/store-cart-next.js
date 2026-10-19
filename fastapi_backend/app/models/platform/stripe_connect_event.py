from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import CreatedAtMixin, IdMixin


class StripeConnectEvent(IdMixin, CreatedAtMixin, Base):
    """One row per Stripe Connect event that was applied (KAN-69).

    The Connect counterpart of ``stripe_events``: a separate endpoint, secret and ledger.
    The unique ``stripe_event_id`` is the idempotency key, inserted in the same transaction
    as the event's side effect, so a rolled-back handler leaves no row and Stripe's retry runs
    it again. ``organization_id`` and ``store_id`` record where the event was routed. Rows hold
    no payload.
    """

    __tablename__ = "stripe_connect_events"

    stripe_event_id: Mapped[str] = mapped_column(unique=True)
    type: Mapped[str]
    stripe_account_id: Mapped[str]
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[str | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL"), index=True
    )
    stripe_created_at: Mapped[datetime]
