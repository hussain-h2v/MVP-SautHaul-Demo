"""Read-only lookups of facility, dock, slot and facility-rule data used by the booking lifecycle.

These modules (facilities, docks, slots) are being extended in parallel and expose no service
functions for these exact reads yet, so the lifecycle reads their tables directly, read-only.
All WRITES stay inside the appointments/facility_checkins tables (see service.py). Recorded in
docs/DECISIONS.md; fold into the owning modules' services when the booking engine (M4) lands."""
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import scope_by_facility
from app.modules.appointments.models import ACTIVE_STATUSES, Appointment
from app.modules.auth.deps import Principal
from app.modules.docks.models import Dock
from app.modules.facilities.models import Facility, FacilityRule
from app.modules.slots.models import AppointmentSlot


async def get_facility(db: AsyncSession, p: Principal, facility_id: UUID) -> Facility | None:
    stmt = scope_by_facility(select(Facility).where(Facility.id == facility_id), Facility.id, p)
    return (await db.execute(stmt)).scalar_one_or_none()


async def facilities_by_ids(db: AsyncSession, ids: list[UUID]) -> dict[UUID, Facility]:
    if not ids:
        return {}
    return {f.id: f for f in (await db.execute(select(Facility).where(Facility.id.in_(ids)))).scalars().all()}


async def docks_by_ids(db: AsyncSession, ids: list[UUID]) -> dict[UUID, Dock]:
    if not ids:
        return {}
    return {d.id: d for d in (await db.execute(select(Dock).where(Dock.id.in_(ids)))).scalars().all()}


async def slots_by_ids(db: AsyncSession, ids: list[UUID]) -> dict[UUID, AppointmentSlot]:
    if not ids:
        return {}
    rows = (await db.execute(select(AppointmentSlot).where(AppointmentSlot.id.in_(ids)))).scalars().all()
    return {s.id: s for s in rows}


async def rule_value(db: AsyncSession, facility_id: UUID, rule_type: str, on: date) -> str | None:
    stmt = (select(FacilityRule.rule_value).where(
        FacilityRule.facility_id == facility_id, FacilityRule.rule_type == rule_type, FacilityRule.active_flag.is_(True),
        or_(FacilityRule.effective_from.is_(None), FacilityRule.effective_from <= on),
        or_(FacilityRule.effective_to.is_(None), FacilityRule.effective_to >= on),
    ).order_by(FacilityRule.effective_from.desc().nulls_last()).limit(1))
    row = (await db.execute(stmt)).first()
    return row[0] if row else None


async def scoped_appointment(db: AsyncSession, p: Principal, appointment_id: UUID):
    """Appointment plus its slot, or None when it does not exist or lies outside the principal's scope."""
    stmt = scope_by_facility(
        select(Appointment, AppointmentSlot).join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(Appointment.id == appointment_id), AppointmentSlot.facility_id, p)
    row = (await db.execute(stmt)).first()
    return (row[0], row[1]) if row else None


async def pending_appointments(db: AsyncSession, p: Principal, facility_id: UUID | None):
    stmt = scope_by_facility(
        select(Appointment, AppointmentSlot).join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(Appointment.appointment_status == "PENDING_CONFIRMATION"), AppointmentSlot.facility_id, p)
    if facility_id:
        stmt = stmt.where(AppointmentSlot.facility_id == facility_id)
    return (await db.execute(stmt.order_by(AppointmentSlot.slot_start_ts))).all()


async def appointments_in_window(db: AsyncSession, facility_id: UUID, start: datetime, end: datetime,
                                 statuses: tuple[str, ...] = ACTIVE_STATUSES):
    stmt = (select(Appointment, AppointmentSlot).join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
            .where(AppointmentSlot.facility_id == facility_id, Appointment.is_current.is_(True),
                   Appointment.appointment_status.in_(statuses),
                   and_(AppointmentSlot.slot_start_ts >= start, AppointmentSlot.slot_start_ts < end)))
    return (await db.execute(stmt.order_by(AppointmentSlot.slot_start_ts))).all()
