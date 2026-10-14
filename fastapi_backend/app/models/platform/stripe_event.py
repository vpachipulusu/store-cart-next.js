from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import CreatedAtMixin, IdMixin


class StripeEvent(IdMixin, CreatedAtMixin, Base):
    """One row per Stripe event that was applied (KAN-44).

    The unique ``stripe_event_id`` is the idempotency key: the row is inserted in
    the same transaction as the state change, so a rolled-back handler leaves no
    row and Stripe's retry is processed again. Rows hold no payload.
    """

    __tablename__ = "stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(unique=True)
    type: Mapped[str]
    stripe_created_at: Mapped[datetime]
