from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK, Versioned

SOURCE_TYPES = ("ORIGINAL_PLAN", "DRIVER_DECLARED", "OPERATIONS_OVERRIDE", "WAREHOUSE_ESTIMATE")
CONFIDENCE_CODES = ("LOW", "MEDIUM", "HIGH")
DELAY_REASON_CODES = ("TRAFFIC", "BREAKDOWN", "WEATHER", "LATE_DEPARTURE", "LOADING_DELAY", "ROUTE_ISSUE", "OTHER")


class EtaUpdate(Base, UUIDPK, Timestamped, Versioned):
    """Append-only ETA history (never overwritten). The effective ETA for a
    shipment is the latest non-superseded row here, falling back to the
    shipment's original_eta_ts (spec section 5, ETA handling)."""

    __tablename__ = "eta_updates"
    __table_args__ = (
        CheckConstraint("source_type IN ('ORIGINAL_PLAN','DRIVER_DECLARED','OPERATIONS_OVERRIDE','WAREHOUSE_ESTIMATE')", name="ck_eta_source"),
        CheckConstraint("confidence_code IN ('LOW','MEDIUM','HIGH')", name="ck_eta_confidence"),
        CheckConstraint(
            "delay_reason_code IS NULL OR delay_reason_code IN "
            "('TRAFFIC','BREAKDOWN','WEATHER','LATE_DEPARTURE','LOADING_DELAY','ROUTE_ISSUE','OTHER')",
            name="ck_eta_delay_reason",
        ),
    )

    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reported_by_driver_id: Mapped[UUID | None] = mapped_column(ForeignKey("drivers.id"))
    declared_eta_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    declared_eta_upper_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence_code: Mapped[str] = mapped_column(String(16), default="MEDIUM", nullable=False)
    delay_reason_code: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(String(1000))
