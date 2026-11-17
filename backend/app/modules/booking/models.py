from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK, Versioned

HOLD_STATUSES = ("active", "converted", "expired", "released")
REQUEST_STATUSES = ("waiting", "approved", "suggested", "held", "rejected", "expired", "escalated")
ESCALATION_STATUSES = ("open", "in_progress", "resolved")


class SlotHold(Base, UUIDPK, Timestamped, Versioned):
    """A time-limited, non-binding reservation. Showing an option is not a hold, and a hold is not a
    promise: only a CONFIRMED appointment is. slot_id is the first slot; a multi-window option lists
    the remaining consecutive slots in extra_slot_ids. DB guarantees (migration 0006): at most one
    active hold per slot and per shipment; every slot of a hold is also protected by slot_claims."""

    __tablename__ = "slot_holds"
    __table_args__ = (
        CheckConstraint("status IN ('active','converted','expired','released')", name="ck_hold_status"),
    )

    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    slot_id: Mapped[UUID] = mapped_column(ForeignKey("appointment_slots.id"), nullable=False, index=True)
    extra_slot_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    requested_exception_id: Mapped[UUID | None] = mapped_column(ForeignKey("driver_exceptions.id"))
    status: Mapped[str] = mapped_column(String(12), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def all_slot_ids(self) -> list[UUID]:
        return [self.slot_id, *[UUID(s) for s in self.extra_slot_ids]]


class SlotClaim(Base, UUIDPK, Timestamped, Versioned):
    """One row per slot covered by an active hold or live appointment. UNIQUE(slot_id) WHERE active makes
    a double allocation impossible even for multi-window bookings."""

    __tablename__ = "slot_claims"
    __table_args__ = (
        CheckConstraint("(hold_id IS NOT NULL) <> (appointment_id IS NOT NULL)", name="ck_claim_one_owner"),
    )

    slot_id: Mapped[UUID] = mapped_column(ForeignKey("appointment_slots.id"), nullable=False, index=True)
    hold_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot_holds.id"), index=True)
    appointment_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointments.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ApprovalRequest(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint("status IN ('waiting','approved','suggested','held','rejected','expired','escalated')",
                        name="ck_request_status"),
    )

    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    exception_id: Mapped[UUID | None] = mapped_column(ForeignKey("driver_exceptions.id"))
    slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointment_slots.id"))
    hold_id: Mapped[UUID | None] = mapped_column(ForeignKey("slot_holds.id"))
    status: Mapped[str] = mapped_column(String(12), default="waiting", nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))
    suggested_slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointment_slots.id"))
    decision_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class Escalation(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "escalations"
    __table_args__ = (
        CheckConstraint("status IN ('open','in_progress','resolved')", name="ck_escalation_status"),
    )

    shipment_id: Mapped[UUID | None] = mapped_column(ForeignKey("shipments.id"), index=True)
    exception_id: Mapped[UUID | None] = mapped_column(ForeignKey("driver_exceptions.id"))
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    handoff_record: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(12), default="open", nullable=False, index=True)
    resolution: Mapped[str | None] = mapped_column(String(1000))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
