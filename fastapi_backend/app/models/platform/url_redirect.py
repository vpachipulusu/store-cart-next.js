from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import IdMixin, TimestampMixin


class UrlRedirect(IdMixin, TimestampMixin, Base):
    __tablename__ = "url_redirects"
    __table_args__ = (
        Index("ix_url_redirects_from_path_enabled", "from_path", "enabled"),
    )

    from_path: Mapped[str] = mapped_column(unique=True)
    to_path: Mapped[str]
    status_code: Mapped[int] = mapped_column(server_default=text("301"))  # 301 or 302
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
