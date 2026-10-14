from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import IdMixin, TimestampMixin


class Organization(IdMixin, TimestampMixin, Base):
    """A merchant business. Subscription state lives here (ADR-010), not on User."""

    __tablename__ = "organizations"

    name: Mapped[str]
    slug: Mapped[str] = mapped_column(unique=True)

    stripe_customer_id: Mapped[str | None] = mapped_column(unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(unique=True)
    stripe_price_id: Mapped[str | None]
    stripe_current_period_end: Mapped[datetime | None]
    # Stripe `created` time of the last subscription event applied (KAN-44); an
    # older event arriving later is ignored.
    stripe_subscription_event_at: Mapped[datetime | None]
    subscription_tier: Mapped[str] = mapped_column(server_default="free")
    subscription_status: Mapped[str] = mapped_column(server_default="inactive")

    # Reserved per-order fee in basis points; stays 0 (ADR-010).
    platform_fee_bps: Mapped[int] = mapped_column(server_default=text("0"))
