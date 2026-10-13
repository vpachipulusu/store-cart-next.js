from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import IdMixin, TimestampMixin


class AppSetting(IdMixin, TimestampMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(unique=True)
    value: Mapped[Any] = mapped_column(JSONB)
    category: Mapped[str] = mapped_column(index=True)  # "general", "features", ...
    description: Mapped[str | None]
