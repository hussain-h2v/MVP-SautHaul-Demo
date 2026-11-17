from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.exceptions.models import DriverException
from app.modules.shipments.models import Shipment

OPEN_STATUSES = ("OPEN", "NEEDS_INFORMATION", "SLOT_OPTIONS_SHARED", "WAITING_CONFIRMATION", "ESCALATED")


async def count_open_for_facility(db: AsyncSession, facility_id: UUID) -> int:
    """Open driver exceptions for shipments destined to the facility (read-only join)."""
    return (await db.execute(
        select(func.count()).select_from(DriverException)
        .join(Shipment, Shipment.id == DriverException.shipment_id)
        .where(Shipment.destination_facility_id == facility_id, DriverException.exception_status.in_(OPEN_STATUSES))
    )).scalar_one()
