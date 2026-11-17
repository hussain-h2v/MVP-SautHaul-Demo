from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK, Versioned


class SystemSetting(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(String(500))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
