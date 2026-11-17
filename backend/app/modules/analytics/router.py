from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.guards import facility_staff
from app.core.listing import csv_response
from app.modules.analytics import service
from app.modules.auth.deps import Principal

router = APIRouter(tags=["analytics"])
read = facility_staff("analytics", "R")


class ReportOut(BaseModel):
    kind: str
    columns: list[str]
    rows: list[dict[str, Any]]


class DockStatusOut(BaseModel):
    active: int
    maintenance: int
    out_of_service: int
    inactive: int
    events_open: int


class FacilityHomeOut(BaseModel):
    date: str
    utilisation_pct: float
    inbound_count: int
    in_yard_count: int
    active_holds: int
    open_exceptions: int
    dock_status: DockStatusOut
    pending_confirmations: int


@router.get("/reports/facility", response_model=ReportOut)
async def facility_report(facility_id: UUID, date_from: date, date_to: date, kind: str,
                          p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.facility_report(db, p, facility_id, date_from, date_to, kind)


@router.get("/reports/facility/export.csv")
async def facility_report_csv(facility_id: UUID, date_from: date, date_to: date, kind: str,
                              p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    r = await service.facility_report(db, p, facility_id, date_from, date_to, kind)
    return csv_response(f"facility-{kind}.csv", r["columns"], r["rows"])


@router.get("/analytics/facility-home", response_model=FacilityHomeOut)
async def facility_home(facility_id: UUID, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.facility_home(db, p, facility_id)
