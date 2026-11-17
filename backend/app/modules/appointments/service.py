from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointments.models import ACTIVE_STATUSES, Appointment, FacilityCheckin


async def for_shipment(db: AsyncSession, shipment_id: UUID) -> list[Appointment]:
    return list((await db.execute(
        select(Appointment).where(Appointment.shipment_id == shipment_id).order_by(Appointment.booked_at)
    )).scalars().all())


async def has_active(db: AsyncSession, shipment_id: UUID) -> bool:
    return (await db.execute(
        select(Appointment.id).where(Appointment.shipment_id == shipment_id,
                                     Appointment.appointment_status.in_(ACTIVE_STATUSES)).limit(1)
    )).first() is not None


async def checkin_for_shipment(db: AsyncSession, shipment_id: UUID) -> FacilityCheckin | None:
    return (await db.execute(select(FacilityCheckin).where(FacilityCheckin.shipment_id == shipment_id))).scalar_one_or_none()


async def for_slots(db: AsyncSession, slot_ids: list[UUID]) -> list[Appointment]:
    if not slot_ids:
        return []
    return list((await db.execute(
        select(Appointment).where(Appointment.slot_id.in_(slot_ids)).order_by(Appointment.booked_at)
    )).scalars().all())


async def active_for_slots(db: AsyncSession, slot_ids: list[UUID]) -> list[Appointment]:
    return [a for a in await for_slots(db, slot_ids) if a.appointment_status in ACTIVE_STATUSES]


async def get(db: AsyncSession, appointment_id: UUID) -> Appointment | None:
    return await db.get(Appointment, appointment_id)


async def current_for_shipments(db: AsyncSession, shipment_ids: list[UUID]) -> dict[UUID, Appointment]:
    """The current appointment per shipment (is_current, newest booking wins)."""
    if not shipment_ids:
        return {}
    rows = (await db.execute(select(Appointment).where(
        Appointment.shipment_id.in_(shipment_ids), Appointment.is_current.is_(True))
        .order_by(Appointment.booked_at))).scalars().all()
    return {a.shipment_id: a for a in rows}


async def get_checkin(db: AsyncSession, checkin_id: UUID) -> FacilityCheckin | None:
    return await db.get(FacilityCheckin, checkin_id)


async def checkins_for_facility(db: AsyncSession, facility_id: UUID) -> list[FacilityCheckin]:
    return list((await db.execute(select(FacilityCheckin).where(FacilityCheckin.facility_id == facility_id)
                                  .order_by(FacilityCheckin.gate_in_ts))).scalars().all())


async def checkins_for_shipments(db: AsyncSession, shipment_ids: list[UUID]) -> dict[UUID, FacilityCheckin]:
    if not shipment_ids:
        return {}
    rows = (await db.execute(select(FacilityCheckin).where(FacilityCheckin.shipment_id.in_(shipment_ids)))).scalars().all()
    return {c.shipment_id: c for c in rows}


async def dock_occupant(db: AsyncSession, dock_id: UUID, exclude: UUID | None = None) -> FacilityCheckin | None:
    stmt = select(FacilityCheckin).where(
        FacilityCheckin.actual_dock_id == dock_id, FacilityCheckin.queue_state == "IN_DOCK",
        FacilityCheckin.unload_end_ts.is_(None))
    if exclude:
        stmt = stmt.where(FacilityCheckin.id != exclude)
    return (await db.execute(stmt)).scalars().first()


async def waiting_count(db: AsyncSession, facility_id: UUID) -> int:
    from sqlalchemy import func

    return (await db.execute(select(func.count()).select_from(FacilityCheckin).where(
        FacilityCheckin.facility_id == facility_id,
        FacilityCheckin.queue_state.in_(("WAITING_EARLY", "WAITING_LATE", "WAITING_DOCK_UNAVAILABLE", "CALLED_TO_DOCK"))
    ))).scalar_one()
