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
from app.modules.booking.models import SlotClaim, SlotHold
from app.modules.docks.models import Dock, DockStatusEvent
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


# ---------------------------------------------------------------- reads used by scheduling and the booking engine
async def facility_docks(db: AsyncSession, facility_id: UUID) -> list[Dock]:
    return list((await db.execute(select(Dock).where(Dock.facility_id == facility_id).order_by(Dock.dock_code))).scalars().all())


async def slots_between(db: AsyncSession, facility_id: UUID, start: datetime, end: datetime):
    return list((await db.execute(
        select(AppointmentSlot).where(AppointmentSlot.facility_id == facility_id, AppointmentSlot.slot_start_ts >= start,
                                      AppointmentSlot.slot_start_ts < end)
        .order_by(AppointmentSlot.dock_id, AppointmentSlot.slot_start_ts))).scalars().all())


async def events_overlapping(db: AsyncSession, dock_ids: list[UUID], start: datetime, end: datetime):
    if not dock_ids:
        return []
    return list((await db.execute(
        select(DockStatusEvent).where(DockStatusEvent.dock_id.in_(dock_ids), DockStatusEvent.event_start_ts < end,
                                      or_(DockStatusEvent.event_end_ts.is_(None), DockStatusEvent.event_end_ts > start))
    )).scalars().all())


async def occupied_slot_ids(db: AsyncSession, slot_ids: list[UUID], now: datetime,
                            ignore_hold_ids: tuple[UUID, ...] = (), ignore_appointment_ids: tuple[UUID, ...] = ()) -> set[UUID]:
    """Slots with an active claim: a live appointment, or a hold that has not expired yet."""
    if not slot_ids:
        return set()
    stmt = (select(SlotClaim.slot_id).join(SlotHold, SlotHold.id == SlotClaim.hold_id, isouter=True)
            .where(SlotClaim.slot_id.in_(slot_ids), SlotClaim.active.is_(True),
                   or_(SlotClaim.appointment_id.is_not(None), SlotHold.expires_at > now)))
    if ignore_hold_ids:
        stmt = stmt.where(or_(SlotClaim.hold_id.is_(None), SlotClaim.hold_id.not_in(ignore_hold_ids)))
    if ignore_appointment_ids:
        stmt = stmt.where(or_(SlotClaim.appointment_id.is_(None), SlotClaim.appointment_id.not_in(ignore_appointment_ids)))
    return {r[0] for r in (await db.execute(stmt)).all()}


async def lock_slots(db: AsyncSession, slot_ids: list[UUID]) -> list[AppointmentSlot]:
    """SELECT ... FOR UPDATE in id order (deadlock-free); concurrent callers for the same slots queue here."""
    rows = (await db.execute(select(AppointmentSlot).where(AppointmentSlot.id.in_(slot_ids))
                             .order_by(AppointmentSlot.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    return list(rows)


async def holds_for_slots(db: AsyncSession, slot_ids: list[UUID], now: datetime) -> dict[UUID, SlotHold]:
    if not slot_ids:
        return {}
    rows = await db.execute(select(SlotClaim.slot_id, SlotHold).join(SlotHold, SlotHold.id == SlotClaim.hold_id)
                            .where(SlotClaim.slot_id.in_(slot_ids), SlotClaim.active.is_(True), SlotHold.expires_at > now))
    return {sid: h for sid, h in rows.all()}


async def claimed_appointments(db: AsyncSession, slot_ids: list[UUID]) -> dict[UUID, UUID]:
    """slot_id -> appointment_id for every slot an appointment claims (covers the extra slots of multi-window bookings)."""
    if not slot_ids:
        return {}
    rows = await db.execute(select(SlotClaim.slot_id, SlotClaim.appointment_id).where(
        SlotClaim.slot_id.in_(slot_ids), SlotClaim.active.is_(True), SlotClaim.appointment_id.is_not(None)))
    return {sid: aid for sid, aid in rows.all()}
