from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned

EXCEPTION_TYPES = ("DELAY", "BREAKDOWN", "TRAFFIC", "WEATHER", "EARLY_ARRIVAL", "DOCK_UNAVAILABLE", "UNKNOWN")
SEVERITY_CODES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
EXCEPTION_STATUSES = (
    "OPEN", "NEEDS_INFORMATION", "SLOT_OPTIONS_SHARED", "WAITING_CONFIRMATION", "RESOLVED", "ESCALATED",
    "DUPLICATE", "CANCELLED",
)


class DriverException(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """A driver-reported delay/exception workflow record — the thing the
    WhatsApp agent creates and the Coordinator portal's inbox/request-detail
    screens work off of (spec sections 7, 11)."""

    __tablename__ = "driver_exceptions"
    __table_args__ = (
        CheckConstraint(
            "exception_type IN ('DELAY','BREAKDOWN','TRAFFIC','WEATHER','EARLY_ARRIVAL','DOCK_UNAVAILABLE','UNKNOWN')",
            name="ck_exception_type",
        ),
        CheckConstraint("reported_delay_min IS NULL OR reported_delay_min >= 0", name="ck_exception_delay_nonneg"),
        CheckConstraint("severity_code IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_exception_severity"),
        CheckConstraint(
            "exception_status IN "
            "('OPEN','NEEDS_INFORMATION','SLOT_OPTIONS_SHARED','WAITING_CONFIRMATION','RESOLVED','ESCALATED','DUPLICATE','CANCELLED')",
            name="ck_exception_status",
        ),
    )

    shipment_id: Mapped[UUID | None] = mapped_column(ForeignKey("shipments.id"), index=True)
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("drivers.id"), nullable=False, index=True)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("chat_threads.id"), nullable=False, index=True)
    exception_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reported_delay_min: Mapped[int | None] = mapped_column(Integer)
    declared_eta_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    earliest_acceptable_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_acceptable_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severity_code: Mapped[str] = mapped_column(String(16), default="MEDIUM", nullable=False)
    exception_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)
