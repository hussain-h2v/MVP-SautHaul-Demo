from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned

DRIVER_STATUSES = ("ACTIVE", "OFF_DUTY", "SUSPENDED", "INACTIVE")


class Driver(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """Reference driver roster, extended per spec section 3/7: a driver has
    no portal login — identity on WhatsApp is the verified E.164 number."""

    __tablename__ = "drivers"
    __table_args__ = (
        CheckConstraint("driver_status IN ('ACTIVE','OFF_DUTY','SUSPENDED','INACTIVE')", name="ck_driver_status"),
    )

    carrier_id: Mapped[UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False, index=True)
    driver_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    licence_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    home_base_city: Mapped[str | None] = mapped_column(String(100))
    driver_status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)

    whatsapp_number: Mapped[str | None] = mapped_column(String(20), unique=True)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_code_hash: Mapped[str | None] = mapped_column(String(64))
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
