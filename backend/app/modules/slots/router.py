from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.db import get_db
from app.modules.auth.deps import Principal, require
from app.modules.slots import service
from app.modules.slots.schemas import (
    BulkStatusIn, BulkStatusOut, CopyDayIn, CopyDayOut, GenerateIn, GenerateOut, ScheduleOut, SlotDetail, SlotOut,
)

router = APIRouter(tags=["slots"])
read = require("docks_slots_rules", "R")
write = require("docks_slots_rules", "W")
grid_read = require("day_schedule", "R")


async def _notify(facility_id: UUID, kind: str) -> None:
    try:
        await events.publish("schedule.changed", {"reason": kind}, facility_id=facility_id)
    except Exception:
        pass


@router.get("/slots", response_model=list[SlotOut])
async def list_slots(facility_id: UUID, date_from: date, date_to: date, dock_id: UUID | None = None,
                     status: str | None = None, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.list_slots(db, p, facility_id, date_from, date_to, dock_id, status)


@router.get("/slots/dates", response_model=list[date])
async def slot_dates(facility_id: UUID, p: Principal = Depends(grid_read), db: AsyncSession = Depends(get_db)):
    return await service.dates(db, p, facility_id)


@router.post("/slots/generate", response_model=GenerateOut)
async def generate_slots(body: GenerateIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    out, _ = await service.generate(db, p, body)
    if not body.dry_run:
        await db.commit()
        await _notify(body.facility_id, "slots.generated")
    return out


@router.post("/slots/bulk-status", response_model=BulkStatusOut)
async def bulk_status(body: BulkStatusIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    out = await service.bulk_status(db, p, body)
    if out.applied:
        await db.commit()
        slots = await service.repository.by_ids(db, p, body.slot_ids)
        for fid in {s.facility_id for s in slots}:
            await _notify(fid, "slots.status")
    return out


@router.post("/slots/copy-day", response_model=CopyDayOut)
async def copy_day(body: CopyDayIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    out = await service.copy_day(db, p, body)
    if not body.dry_run:
        await db.commit()
        await _notify(body.facility_id, "slots.copied")
    return out


@router.get("/schedule", response_model=ScheduleOut)
async def schedule(facility_id: UUID, day: date = Query(alias="date"), p: Principal = Depends(grid_read),
                   db: AsyncSession = Depends(get_db)):
    return await service.schedule(db, p, facility_id, day)


@router.get("/schedule/slots/{slot_id}", response_model=SlotDetail)
async def slot_detail(slot_id: UUID, p: Principal = Depends(grid_read), db: AsyncSession = Depends(get_db)):
    return await service.slot_detail(db, p, slot_id)
