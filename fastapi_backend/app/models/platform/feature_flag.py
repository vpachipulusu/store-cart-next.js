from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import IdMixin, TimestampMixin


class FeatureFlag(IdMixin, TimestampMixin, Base):
    __tablename__ = "feature_flags"
    __table_args__ = (Index("ix_feature_flags_name_enabled", "name", "enabled"),)

    name: Mapped[str] = mapped_column(unique=True)
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    description: Mapped[str | None]
    rollout_percentage: Mapped[int] = mapped_column(server_default=text("0"))  # 0-100
