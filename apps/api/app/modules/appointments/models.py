from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned

APPOINTMENT_STATUSES = (
    "PENDING_CONFIRMATION", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW", "REJECTED",
)
BOOKING_SOURCES = ("PLANNER", "DRIVER_CHAT", "WAREHOUSE", "SCHEDULING_TOOL", "MANUAL_OVERRIDE")
ARRIVAL_STATES = ("EARLY", "ON_TIME", "LATE", "NO_SHOW")
QUEUE_STATES = (
    "NOT_QUEUED", "WAITING_EARLY", "WAITING_LATE", "WAITING_DOCK_UNAVAILABLE", "CALLED_TO_DOCK", "IN_DOCK",
    "COMPLETED",
)


class Appointment(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """The booking state machine (spec section 5). The two partial unique
    indexes that make double-booking impossible — one active booking per
    slot, one current active appointment per shipment — are added via raw
    SQL in the initial migration (SQLAlchemy can declare partial indexes,
    but we keep them next to the EXCLUDE constraint for one audited block)."""

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "appointment_status IN "
            "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS','COMPLETED','CANCELLED','NO_SHOW','REJECTED')",
            name="ck_appointment_status",
        ),
        CheckConstraint(
            "booking_source IN ('PLANNER','DRIVER_CHAT','WAREHOUSE','SCHEDULING_TOOL','MANUAL_OVERRIDE')",
            name="ck_appointment_source",
        ),
    )

    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    slot_id: Mapped[UUID] = mapped_column(ForeignKey("appointment_slots.id"), nullable=False, index=True)
    appointment_status: Mapped[str] = mapped_column(String(24), nullable=False)
    booking_source: Mapped[str] = mapped_column(String(24), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    replaced_appointment_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointments.id"))
    warehouse_confirmation_ref: Mapped[str | None] = mapped_column(String(100))


class FacilityCheckin(Base, UUIDPK, Timestamped, Versioned):
    """Yard/gate state for one shipment's current visit (spec: Facility
    portal "Yard and gate" screen). A mismatch between the planned dock on
    the active appointment and actual_dock_id is a human-review trigger,
    never silently auto-reconciled (reference audit finding on
    facility_checkins vs. appointment drift)."""

    __tablename__ = "facility_checkins"
    __table_args__ = (
        CheckConstraint(
            "arrival_state IS NULL OR arrival_state IN ('EARLY','ON_TIME','LATE','NO_SHOW')",
            name="ck_checkin_arrival_state",
        ),
        CheckConstraint(
            "queue_state IS NULL OR queue_state IN "
            "('NOT_QUEUED','WAITING_EARLY','WAITING_LATE','WAITING_DOCK_UNAVAILABLE','CALLED_TO_DOCK','IN_DOCK','COMPLETED')",
            name="ck_checkin_queue_state",
        ),
        CheckConstraint("queue_position IS NULL OR queue_position > 0", name="ck_checkin_queue_position"),
    )

    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id"), unique=True, nullable=False)
    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    gate_in_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    yard_queue_enter_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dock_in_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unload_start_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unload_end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gate_out_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrival_state: Mapped[str | None] = mapped_column(String(16))
    queue_state: Mapped[str | None] = mapped_column(String(32))
    queue_position: Mapped[int | None] = mapped_column(Integer)
    actual_dock_id: Mapped[UUID | None] = mapped_column(ForeignKey("docks.id"))
    notes: Mapped[str | None] = mapped_column(String(1000))
