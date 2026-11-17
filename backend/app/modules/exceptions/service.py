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


OPEN_STATUSES = ("OPEN", "NEEDS_INFORMATION", "SLOT_OPTIONS_SHARED", "WAITING_CONFIRMATION")


async def get_exception(db, exception_id):
    from app.modules.exceptions.models import DriverException

    return await db.get(DriverException, exception_id)


async def list_open(db, limit: int = 200):
    from sqlalchemy import select

    from app.modules.exceptions.models import DriverException

    rows = await db.execute(select(DriverException).where(DriverException.exception_status.in_(OPEN_STATUSES))
                            .order_by(DriverException.reported_at.desc()).limit(limit))
    return list(rows.scalars().all())
