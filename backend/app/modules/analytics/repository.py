"""Read-model queries for facility reports and the facility home. Read-only joins across the
slots, appointments, check-in, dock and shipment tables; nothing here writes."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointments.models import Appointment, FacilityCheckin
from app.modules.docks.models import Dock, DockStatusEvent
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot

BOOKED = ("PENDING_CONFIRMATION", "CONFIRMED", "IN_PROGRESS", "COMPLETED")


async def slots_with_booking(db: AsyncSession, facility_id: UUID, start: datetime, end: datetime):
    """[(slot, dock_code, booked)] for slots starting in [start, end)."""
    slots = (await db.execute(
        select(AppointmentSlot, Dock.dock_code).join(Dock, Dock.id == AppointmentSlot.dock_id)
        .where(AppointmentSlot.facility_id == facility_id, AppointmentSlot.slot_start_ts >= start,
               AppointmentSlot.slot_start_ts < end))).all()
    ids = [s.id for s, _ in slots]
    booked: set[UUID] = set()
    if ids:
        booked = set((await db.execute(select(Appointment.slot_id).where(
            Appointment.slot_id.in_(ids), Appointment.appointment_status.in_(BOOKED)))).scalars().all())
    return [(s, code, s.id in booked) for s, code in slots]


async def checkins_in_window(db: AsyncSession, facility_id: UUID, start: datetime, end: datetime):
    return (await db.execute(
        select(FacilityCheckin, Shipment).join(Shipment, Shipment.id == FacilityCheckin.shipment_id)
        .where(FacilityCheckin.facility_id == facility_id, FacilityCheckin.gate_in_ts >= start,
               FacilityCheckin.gate_in_ts < end).order_by(FacilityCheckin.gate_in_ts))).all()


async def appointments_in_window(db: AsyncSession, facility_id: UUID, start: datetime, end: datetime):
    """[(appointment_status, slot_start_ts)] for appointments whose slot starts in the window."""
    return (await db.execute(
        select(Appointment.appointment_status, AppointmentSlot.slot_start_ts)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(AppointmentSlot.facility_id == facility_id, AppointmentSlot.slot_start_ts >= start,
               AppointmentSlot.slot_start_ts < end,
               Appointment.appointment_status.in_(BOOKED + ("NO_SHOW",))))).all()


async def dock_status_counts(db: AsyncSession, facility_id: UUID, now: datetime) -> dict[str, int]:
    rows = (await db.execute(select(Dock.dock_status, func.count()).where(Dock.facility_id == facility_id)
                             .group_by(Dock.dock_status))).all()
    by = dict(rows)
    events_open = (await db.execute(
        select(func.count()).select_from(DockStatusEvent).join(Dock, Dock.id == DockStatusEvent.dock_id)
        .where(Dock.facility_id == facility_id,
               or_(DockStatusEvent.event_end_ts.is_(None), DockStatusEvent.event_end_ts > now),
               DockStatusEvent.event_type != "REOPENED"))).scalar_one()
    return {"active": by.get("ACTIVE", 0), "maintenance": by.get("MAINTENANCE", 0),
            "out_of_service": by.get("OUT_OF_SERVICE", 0), "inactive": by.get("INACTIVE", 0),
            "events_open": events_open}
