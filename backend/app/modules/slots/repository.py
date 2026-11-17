from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import scope_by_facility
from app.modules.auth.deps import Principal
from app.modules.slots.models import AppointmentSlot


async def list_slots(db: AsyncSession, p: Principal, facility_id: UUID, start: datetime, end: datetime,
                     dock_id: UUID | None = None, status: str | None = None):
    stmt = scope_by_facility(select(AppointmentSlot), AppointmentSlot.facility_id, p).where(
        AppointmentSlot.facility_id == facility_id, AppointmentSlot.slot_start_ts >= start,
        AppointmentSlot.slot_start_ts < end)
    if dock_id:
        stmt = stmt.where(AppointmentSlot.dock_id == dock_id)
    if status:
        stmt = stmt.where(AppointmentSlot.slot_status == status)
    return (await db.execute(stmt.order_by(AppointmentSlot.dock_id, AppointmentSlot.slot_start_ts))).scalars().all()


async def get_slot(db: AsyncSession, p: Principal, slot_id: UUID) -> AppointmentSlot | None:
    stmt = scope_by_facility(select(AppointmentSlot).where(AppointmentSlot.id == slot_id),
                             AppointmentSlot.facility_id, p)
    return (await db.execute(stmt)).scalar_one_or_none()


async def by_ids(db: AsyncSession, p: Principal, ids: list[UUID]) -> list[AppointmentSlot]:
    stmt = scope_by_facility(select(AppointmentSlot).where(AppointmentSlot.id.in_(ids)),
                             AppointmentSlot.facility_id, p)
    return list((await db.execute(stmt)).scalars().all())


async def existing_windows(db: AsyncSession, dock_ids: list[UUID], start: datetime, end: datetime):
    """(dock_id, start, end) of every slot overlapping [start, end) on the given docks."""
    if not dock_ids:
        return []
    rows = await db.execute(select(AppointmentSlot.dock_id, AppointmentSlot.slot_start_ts, AppointmentSlot.slot_end_ts)
                            .where(AppointmentSlot.dock_id.in_(dock_ids), AppointmentSlot.slot_start_ts < end,
                                   AppointmentSlot.slot_end_ts > start))
    return [tuple(r) for r in rows.all()]


async def dates_with_slots(db: AsyncSession, p: Principal, facility_id: UUID, tz: str) -> list:
    from sqlalchemy import func

    local = func.timezone(tz, AppointmentSlot.slot_start_ts)
    stmt = scope_by_facility(select(func.date(local).label("d")).where(AppointmentSlot.facility_id == facility_id),
                             AppointmentSlot.facility_id, p).group_by("d").order_by("d")
    return [r[0] for r in (await db.execute(stmt)).all()]
