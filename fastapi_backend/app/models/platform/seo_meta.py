from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import IdMixin, TimestampMixin


class SeoMeta(IdMixin, TimestampMixin, Base):
    __tablename__ = "seo_meta"

    page: Mapped[str] = mapped_column(unique=True)  # e.g. "/", "/pricing"
    title: Mapped[str]
    description: Mapped[str]
    keywords: Mapped[str | None]
    og_title: Mapped[str | None]
    og_description: Mapped[str | None]
    og_image: Mapped[str | None]
    twitter_card: Mapped[str | None] = mapped_column(
        server_default="summary_large_image"
    )
    canonical: Mapped[str | None]
    noindex: Mapped[bool] = mapped_column(server_default=text("false"))
    nofollow: Mapped[bool] = mapped_column(server_default=text("false"))
