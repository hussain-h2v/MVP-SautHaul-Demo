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
