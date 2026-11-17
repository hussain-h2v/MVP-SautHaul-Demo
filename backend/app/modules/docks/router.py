from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import get_db
from app.modules.auth.deps import Principal, require
from app.modules.docks import service
from app.modules.docks.schemas import (
    AffectedList, DockEventCreated, DockEventIn, DockEventOut, DockEventPreviewIn, DockIn, DockOut, DockPatch,
)

router = APIRouter(tags=["docks"])
read = require("docks_slots_rules", "R")
write = require("docks_slots_rules", "W")


async def _notify(facility_id: UUID, kind: str) -> None:
    try:
        await events.publish("schedule.changed", {"reason": kind}, facility_id=facility_id)
    except Exception:
        pass


@router.get("/docks", response_model=list[DockOut])
async def list_docks(facility_id: UUID | None = None, status: str | None = None,
                     p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return [DockOut.model_validate(d) for d in await service.list_docks(db, p, facility_id, status)]


@router.post("/docks", response_model=DockOut, status_code=201)
async def create_dock(body: DockIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    d = await service.create_dock(db, p, body)
    await db.commit()
    return DockOut.model_validate(d)


@router.patch("/docks/{dock_id}", response_model=DockOut)
async def update_dock(dock_id: UUID, body: DockPatch, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    d = await service.update_dock(db, p, dock_id, body)
    await db.commit()
    await _notify(d.facility_id, "dock.updated")
    return DockOut.model_validate(d)


@router.delete("/docks/{dock_id}", response_model=DockOut)
async def retire_dock(dock_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    d = await service.retire_dock(db, p, dock_id)
    await db.commit()
    await _notify(d.facility_id, "dock.retired")
    return DockOut.model_validate(d)


@router.get("/dock-events", response_model=list[DockEventOut])
async def list_dock_events(facility_id: UUID | None = None, date_from: datetime | None = None,
                           date_to: datetime | None = None, open_only: bool = False,
                           p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.list_events(db, p, facility_id, date_from, date_to, open_only)


@router.post("/dock-events/preview", response_model=AffectedList)
async def preview_dock_event(body: DockEventPreviewIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    dock = await service.get_in_scope(db, p, body.dock_id)
    return AffectedList(affected_appointments=await service.affected_for_window(
        db, dock.id, body.event_start_ts, body.event_end_ts))


@router.post("/dock-events", response_model=DockEventCreated, status_code=201)
async def create_dock_event(body: DockEventIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    e, dock, affected = await service.create_event(db, p, body)
    await db.commit()
    await _notify(dock.facility_id, "dock.event")
    return service.created_out(e, dock, affected)


@router.post("/dock-events/{event_id}/resolve", response_model=DockEventOut)
async def resolve_dock_event(event_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    e, dock = await service.resolve_event(db, p, event_id)
    await db.commit()
    await _notify(dock.facility_id, "dock.event.resolved")
    return service._event_out(e, dock.dock_code, datetime.now(e.event_end_ts.tzinfo), 0)
