from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.listing import ImportResult, csv_response
from app.modules.auth.deps import Principal, get_principal, require
from app.modules.vehicles import repository, service
from app.modules.vehicles.schemas import VehicleIn, VehicleOut, VehiclePage, VehiclePatch

router = APIRouter(prefix="/vehicle-types", tags=["vehicles"])
vehicles_router = APIRouter(prefix="/vehicles", tags=["vehicles"])
read = require("drivers_vehicles", "R")
write = require("drivers_vehicles", "W")
CSV_FIELDS = ["code", "registration_number", "vehicle_type_code", "capacity_kg", "refrigeration_capable",
              "heavy_capable", "active_flag", "assigned_shipments"]


class VehicleTypeOut(BaseModel):
    code: str
    description: str


@router.get("", response_model=list[VehicleTypeOut])
async def vehicle_types(_: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    return [VehicleTypeOut(code=t.code, description=t.description) for t in await service.list_types(db)]


@vehicles_router.get("", response_model=VehiclePage)
async def list_vehicles(
    q: str | None = None, active: bool | None = None, type: str | None = None, sort: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    p: Principal = Depends(read), db: AsyncSession = Depends(get_db),
):
    return await service.page(db, p, (q, active, type), sort, limit, offset)


@vehicles_router.get("/export.csv")
async def export_vehicles(q: str | None = None, active: bool | None = None, type: str | None = None,
                          sort: str | None = None, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    rows = await service.enrich(db, [(r[0], r[1]) for r in await repository.list_all(db, p, (q, active, type), sort)])
    return csv_response("vehicles.csv", CSV_FIELDS, [r.model_dump() for r in rows])


@vehicles_router.post("/import", response_model=ImportResult)
async def import_vehicles(dry_run: bool = True, file: UploadFile = File(...), p: Principal = Depends(write),
                          db: AsyncSession = Depends(get_db)):
    result = await service.import_csv(db, p, file, dry_run)
    if not dry_run and not result.errors:
        await db.commit()
    return result


@vehicles_router.post("", response_model=VehicleOut, status_code=201)
async def create_vehicle(body: VehicleIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    v = await service.create(db, p, body)
    await db.commit()
    t = (await service.get_scoped(db, p, v.id))[1]
    return (await service.enrich(db, [(v, t)]))[0]


@vehicles_router.patch("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(vehicle_id: UUID, body: VehiclePatch, p: Principal = Depends(write),
                         db: AsyncSession = Depends(get_db)):
    v = await service.update(db, p, vehicle_id, body)
    await db.commit()
    t = (await service.get_scoped(db, p, v.id))[1]
    return (await service.enrich(db, [(v, t)]))[0]


@vehicles_router.delete("/{vehicle_id}", response_model=VehicleOut)
async def retire_vehicle(vehicle_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    v = await service.retire(db, p, vehicle_id)
    await db.commit()
    t = (await service.get_scoped(db, p, v.id))[1]
    return (await service.enrich(db, [(v, t)]))[0]
