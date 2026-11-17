from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.listing import csv_response
from app.modules.auth.deps import Principal, require
from app.modules.carriers import repository, service
from app.modules.carriers.schemas import CarrierDetail, CarrierIn, CarrierOut, CarrierPage, CarrierPatch

router = APIRouter(prefix="/carriers", tags=["carriers"])
read = require("drivers_vehicles", "R")
write = require("manage_master", "W")
CSV_FIELDS = ["code", "carrier_name", "contact_email", "contact_phone", "active_flag", "driver_count", "vehicle_count"]


@router.get("", response_model=CarrierPage)
async def list_carriers(
    q: str | None = None, active: bool | None = None, sort: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    p: Principal = Depends(read), db: AsyncSession = Depends(get_db),
):
    total, rows = await repository.list_page(db, p, q, active, sort, limit, offset)
    return CarrierPage(total=total, items=await service.enrich(db, list(rows)))


@router.get("/export.csv")
async def export_carriers(q: str | None = None, active: bool | None = None, sort: str | None = None,
                          p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    rows = await service.enrich(db, list(await repository.list_all(db, p, q, active, sort)))
    return csv_response("carriers.csv", CSV_FIELDS, [r.model_dump() for r in rows])


@router.get("/{carrier_id}", response_model=CarrierDetail)
async def get_carrier(carrier_id: UUID, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.detail(db, p, carrier_id)


@router.post("", response_model=CarrierOut, status_code=201)
async def create_carrier(body: CarrierIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    c = await service.create(db, body)
    await db.commit()
    return (await service.enrich(db, [c]))[0]


@router.patch("/{carrier_id}", response_model=CarrierOut)
async def update_carrier(carrier_id: UUID, body: CarrierPatch, p: Principal = Depends(write),
                         db: AsyncSession = Depends(get_db)):
    c = await service.update(db, p, carrier_id, body)
    await db.commit()
    return (await service.enrich(db, [c]))[0]
