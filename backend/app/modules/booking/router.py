from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.guards import facility_staff
from app.modules.auth.deps import Principal
from app.modules.booking import service
from app.modules.booking.schemas import (
    AppointmentOut, AssignDockIn, CheckInIn, FinishOut, InboundRow, NoShowIn, PendingOut, RejectIn, YardOut, YardRow,
)

router = APIRouter(tags=["booking"])
read = facility_staff("day_schedule", "R")
write = facility_staff("day_schedule", "W")


def _appt(a) -> AppointmentOut:
    return AppointmentOut(appointment_id=a.id, code=a.code, appointment_status=a.appointment_status,
                          is_current=a.is_current)


@router.get("/appointments/pending", response_model=list[PendingOut])
async def pending(facility_id: UUID | None = None, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.pending(db, p, facility_id)


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentOut)
async def confirm(appointment_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    a, facility_id = await service.confirm(db, p, appointment_id)
    await db.commit()
    await service.publish_change(facility_id, "appointment.confirmed", appointment_id=str(a.id))
    return _appt(a)


@router.post("/appointments/{appointment_id}/reject", response_model=AppointmentOut)
async def reject(appointment_id: UUID, body: RejectIn, p: Principal = Depends(write),
                 db: AsyncSession = Depends(get_db)):
    a, facility_id = await service.reject(db, p, appointment_id, body.reason)
    await db.commit()
    await service.publish_change(facility_id, "appointment.rejected", appointment_id=str(a.id))
    return _appt(a)


@router.get("/yard", response_model=YardOut)
async def yard(facility_id: UUID, date: date | None = None, p: Principal = Depends(read),
               db: AsyncSession = Depends(get_db)):
    return await service.yard(db, p, facility_id, date)


@router.post("/yard/check-in", response_model=YardRow, status_code=201)
async def check_in(body: CheckInIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row, facility_id = await service.check_in(db, p, body.shipment_id)
    await db.commit()
    await service.publish_change(facility_id, "yard.check_in", shipment_id=str(body.shipment_id))
    return row


@router.post("/yard/no-show", response_model=AppointmentOut)
async def no_show(body: NoShowIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    a, facility_id = await service.no_show(db, p, body.appointment_id)
    await db.commit()
    await service.publish_change(facility_id, "appointment.no_show", appointment_id=str(a.id))
    return _appt(a)


@router.post("/yard/{checkin_id}/assign-dock", response_model=YardRow)
async def assign_dock(checkin_id: UUID, body: AssignDockIn, p: Principal = Depends(write),
                      db: AsyncSession = Depends(get_db)):
    row, facility_id = await service.assign_dock(db, p, checkin_id, body.dock_id)
    await db.commit()
    await service.publish_change(facility_id, "yard.dock_assigned", checkin_id=str(checkin_id))
    return row


@router.post("/yard/{checkin_id}/start-unload", response_model=YardRow)
async def start_unload(checkin_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row, facility_id = await service.start_unload(db, p, checkin_id)
    await db.commit()
    await service.publish_change(facility_id, "yard.unload_started", checkin_id=str(checkin_id))
    return row


@router.post("/yard/{checkin_id}/finish-unload", response_model=FinishOut)
async def finish_unload(checkin_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row, facility_id = await service.finish_unload(db, p, checkin_id)
    await db.commit()
    await service.publish_change(facility_id, "yard.unload_finished", checkin_id=str(checkin_id))
    return row


@router.post("/yard/{checkin_id}/gate-out", response_model=YardRow)
async def gate_out(checkin_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row, facility_id = await service.gate_out(db, p, checkin_id)
    await db.commit()
    await service.publish_change(facility_id, "yard.gate_out", checkin_id=str(checkin_id))
    return row


@router.get("/inbound", response_model=list[InboundRow])
async def inbound(facility_id: UUID, date: date | None = None, p: Principal = Depends(read),
                  db: AsyncSession = Depends(get_db)):
    return await service.inbound(db, p, facility_id, date)
