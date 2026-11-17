"""Read-only queries for the live operations board (direct reads; no service exposes this cross-table view yet)."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.docks.models import Dock
from app.modules.facilities.models import Facility
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot

STAGE_STATUSES = ("ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK", "COMPLETED")


async def candidates(db: AsyncSession, facility_id: UUID | None):
    stmt = (select(Shipment, Facility.code, Facility.timezone)
            .join(Facility, Facility.id == Shipment.destination_facility_id)
            .where(Shipment.offer_status == "accepted", Shipment.driver_id.is_not(None),
                   Shipment.current_status.in_(STAGE_STATUSES)))
    if facility_id:
        stmt = stmt.where(Shipment.destination_facility_id == facility_id)
    return (await db.execute(stmt.order_by(Shipment.code))).all()


async def slot_info(db: AsyncSession, slot_ids: list[UUID]) -> dict[UUID, tuple[str, str, object]]:
    if not slot_ids:
        return {}
    rows = await db.execute(
        select(AppointmentSlot.id, AppointmentSlot.code, Dock.dock_code, AppointmentSlot.slot_start_ts)
        .join(Dock, Dock.id == AppointmentSlot.dock_id).where(AppointmentSlot.id.in_(slot_ids)))
    return {i: (c, d, s) for i, c, d, s in rows.all()}
