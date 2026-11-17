from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import scope_by_facility
from app.modules.auth.deps import Principal
from app.modules.docks.models import Dock, DockStatusEvent


async def list_docks(db: AsyncSession, p: Principal, facility_id: UUID | None, status: str | None):
    stmt = scope_by_facility(select(Dock), Dock.facility_id, p)
    if facility_id:
        stmt = stmt.where(Dock.facility_id == facility_id)
    if status:
        stmt = stmt.where(Dock.dock_status == status)
    return (await db.execute(stmt.order_by(Dock.facility_id, Dock.dock_code))).scalars().all()


async def get_dock(db: AsyncSession, p: Principal, dock_id: UUID) -> Dock | None:
    stmt = scope_by_facility(select(Dock).where(Dock.id == dock_id), Dock.facility_id, p)
    return (await db.execute(stmt)).scalar_one_or_none()


async def by_facility_code(db: AsyncSession, facility_id: UUID, dock_code: str) -> Dock | None:
    return (await db.execute(select(Dock).where(Dock.facility_id == facility_id,
                                                Dock.dock_code == dock_code))).scalar_one_or_none()


async def docks_by_ids(db: AsyncSession, ids: list[UUID]) -> dict[UUID, Dock]:
    if not ids:
        return {}
    return {d.id: d for d in (await db.execute(select(Dock).where(Dock.id.in_(ids)))).scalars().all()}


def _overlap(start: datetime, end: datetime | None):
    cond = [DockStatusEvent.event_end_ts.is_(None) | (DockStatusEvent.event_end_ts > start)]
    if end is not None:
        cond.append(DockStatusEvent.event_start_ts < end)
    return and_(*cond)


async def events_for(db: AsyncSession, dock_ids: list[UUID], date_from: datetime | None, date_to: datetime | None,
                     open_only: bool, now: datetime):
    if not dock_ids:
        return []
    stmt = select(DockStatusEvent).where(DockStatusEvent.dock_id.in_(dock_ids))
    if date_from is not None:
        stmt = stmt.where(or_(DockStatusEvent.event_end_ts.is_(None), DockStatusEvent.event_end_ts > date_from))
    if date_to is not None:
        stmt = stmt.where(DockStatusEvent.event_start_ts < date_to)
    if open_only:
        stmt = stmt.where(or_(DockStatusEvent.event_end_ts.is_(None), DockStatusEvent.event_end_ts > now))
    return (await db.execute(stmt.order_by(DockStatusEvent.event_start_ts.desc()))).scalars().all()


async def get_event(db: AsyncSession, event_id: UUID) -> DockStatusEvent | None:
    return await db.get(DockStatusEvent, event_id)
