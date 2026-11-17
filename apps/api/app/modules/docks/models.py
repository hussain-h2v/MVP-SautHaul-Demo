from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned

DOCK_TYPES = ("STANDARD", "REEFER", "HEAVY")
DOCK_STATUSES = ("ACTIVE", "MAINTENANCE", "OUT_OF_SERVICE", "INACTIVE")
DOCK_EVENT_TYPES = ("MAINTENANCE", "BREAKDOWN", "CAPACITY_REDUCTION", "REOPENED", "MANUAL_BLOCK")


class Dock(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    __tablename__ = "docks"
    __table_args__ = (
        CheckConstraint("dock_type IN ('STANDARD','REEFER','HEAVY')", name="ck_dock_type"),
        CheckConstraint(
            "dock_status IN ('ACTIVE','MAINTENANCE','OUT_OF_SERVICE','INACTIVE')", name="ck_dock_status"
        ),
        CheckConstraint("max_vehicle_weight_kg > 0", name="ck_dock_weight_positive"),
        UniqueConstraint("facility_id", "dock_code", name="uq_dock_facility_code"),
    )

    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    dock_code: Mapped[str] = mapped_column(String(32), nullable=False)
    dock_type: Mapped[str] = mapped_column(String(16), nullable=False)
    supports_refrigerated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_vehicle_weight_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    dock_status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)


class DockStatusEvent(Base, UUIDPK, Timestamped, Versioned):
    """Breakdown / maintenance / reduced-capacity events. An event with
    event_end_ts IS NULL is still active; the scheduling service treats any
    slot whose window overlaps [event_start_ts, event_end_ts) as infeasible
    (reference audit finding A, docs/DATA_AUDIT.md)."""

    __tablename__ = "dock_status_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('MAINTENANCE','BREAKDOWN','CAPACITY_REDUCTION','REOPENED','MANUAL_BLOCK')",
            name="ck_dock_event_type",
        ),
        CheckConstraint("event_end_ts IS NULL OR event_end_ts > event_start_ts", name="ck_dock_event_order"),
    )

    dock_id: Mapped[UUID] = mapped_column(ForeignKey("docks.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
