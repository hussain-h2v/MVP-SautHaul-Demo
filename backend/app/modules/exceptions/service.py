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


async def open_for_thread(db, thread_id, shipment_id):
    from sqlalchemy import select

    from app.modules.exceptions.models import DriverException

    return (await db.execute(select(DriverException).where(
        DriverException.thread_id == thread_id, DriverException.shipment_id == shipment_id,
        DriverException.exception_status.in_(("OPEN", "NEEDS_INFORMATION", "SLOT_OPTIONS_SHARED", "WAITING_CONFIRMATION")))
        .order_by(DriverException.reported_at.desc()).limit(1))).scalar_one_or_none()


async def create_from_agent(db, *, shipment_id, driver_id, thread_id, exception_type, description, severity="MEDIUM",
                            reported_delay_min=None, declared_eta_ts=None, latest_acceptable_ts=None, status="NEEDS_INFORMATION"):
    import uuid
    from datetime import UTC, datetime

    from app.modules.exceptions.models import DriverException

    e = DriverException(code=f"EXA{uuid.uuid4().hex[:12]}", shipment_id=shipment_id, driver_id=driver_id, thread_id=thread_id,
                        exception_type=exception_type, reported_at=datetime.now(UTC), reported_delay_min=reported_delay_min,
                        declared_eta_ts=declared_eta_ts, latest_acceptable_ts=latest_acceptable_ts, severity_code=severity,
                        exception_status=status, description=description[:1900])
    db.add(e)
    await db.flush()
    return e


async def set_status(db, exception_id, status):
    from app.modules.exceptions.models import DriverException

    e = await db.get(DriverException, exception_id) if exception_id else None
    if e is not None:
        e.exception_status = status
    return e
