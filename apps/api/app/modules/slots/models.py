from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned

SLOT_STATUSES = ("OPEN", "BLOCKED", "CLOSED")


class AppointmentSlot(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """A bookable time window on one dock. Non-overlap on the same dock is
    additionally enforced by a Postgres EXCLUDE constraint using tstzrange
    (spec section 3, integrity rule 4) — added via raw SQL in the initial
    migration, since SQLAlchemy has no declarative EXCLUDE construct."""

    __tablename__ = "appointment_slots"
    __table_args__ = (
        CheckConstraint("slot_end_ts > slot_start_ts", name="ck_slot_order"),
        CheckConstraint("slot_status IN ('OPEN','BLOCKED','CLOSED')", name="ck_slot_status"),
        UniqueConstraint("dock_id", "slot_start_ts", "slot_end_ts", name="uq_slot_dock_window"),
    )

    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    dock_id: Mapped[UUID] = mapped_column(ForeignKey("docks.id"), nullable=False, index=True)
    slot_start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slot_end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slot_status: Mapped[str] = mapped_column(String(16), default="OPEN", nullable=False)
    block_reason: Mapped[str | None] = mapped_column(String(500))
