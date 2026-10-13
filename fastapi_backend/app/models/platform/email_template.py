from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.models.platform.mixins import IdMixin, TimestampMixin


class EmailTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "email_templates"

    name: Mapped[str] = mapped_column(unique=True)  # "welcome", "password-reset"
    subject: Mapped[str]
    html_body: Mapped[str]
    text_body: Mapped[str | None]
    variables: Mapped[Any | None] = mapped_column(JSONB)  # variable names used
