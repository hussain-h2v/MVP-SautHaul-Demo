from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import ForbiddenError
from app.core.listing import csv_response
from app.modules.auth.deps import Principal, require
from app.modules.carriers import portal_service as service
from app.modules.carriers.portal_schemas import CarrierReport, DashboardOut, SlotChange, TrackerPage

router = APIRouter(prefix="/carrier", tags=["carrier-portal"])
reports_router = APIRouter(prefix="/reports/carrier", tags=["carrier-portal"])
PORTAL_ROLES = ("carrier_user", "admin", "coordinator")


def portal(capability: str):
    """Carrier users see their own company; admin and coordinators may look at any carrier. Planners are not part of
    this portal."""
    base = require(capability, "R")

    async def dep(p: Principal = Depends(base)) -> Principal:
        if p.role not in PORTAL_ROLES:
            raise ForbiddenError("Not available for this role")
        return p

    return dep


tracker_read = portal("shipment_details")
report_read = portal("analytics")


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(carrier_id: UUID | None = None, p: Principal = Depends(tracker_read), db: AsyncSession = Depends(get_db)):
    return await service.dashboard(db, p, service.resolve_carrier(p, carrier_id))


@router.get("/tracker", response_model=TrackerPage)
async def tracker(carrier_id: UUID | None = None, q: str | None = None, status: str | None = None,
                  facility_id: UUID | None = None, driver_id: UUID | None = None,
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  p: Principal = Depends(tracker_read), db: AsyncSession = Depends(get_db)):
    """Read-only picture of every shipment: no edit actions exist anywhere behind this endpoint."""
    return await service.tracker(db, p, service.resolve_carrier(p, carrier_id), q, status, facility_id, driver_id, limit, offset)


@router.get("/slot-changes", response_model=list[SlotChange])
async def slot_changes(carrier_id: UUID | None = None, limit: int = Query(50, ge=1, le=200),
                       p: Principal = Depends(tracker_read), db: AsyncSession = Depends(get_db)):
    return await service.slot_changes(db, p, service.resolve_carrier(p, carrier_id), limit)


@reports_router.get("", response_model=CarrierReport)
async def carrier_report(kind: str, date_from: date, date_to: date, carrier_id: UUID | None = None,
                         p: Principal = Depends(report_read), db: AsyncSession = Depends(get_db)):
    return await service.report(db, p, service.resolve_carrier(p, carrier_id), kind, date_from, date_to)


@reports_router.get("/export.csv")
async def carrier_report_csv(kind: str, date_from: date, date_to: date, carrier_id: UUID | None = None,
                             p: Principal = Depends(report_read), db: AsyncSession = Depends(get_db)):
    r = await service.report(db, p, service.resolve_carrier(p, carrier_id), kind, date_from, date_to)
    return csv_response(f"carrier-{kind}.csv", r.columns, r.rows)
