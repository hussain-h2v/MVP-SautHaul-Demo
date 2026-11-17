from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.idempotency import get_redis
from app.core.listing import ImportResult, csv_response
from app.modules.auth.deps import Principal, require
from app.modules.drivers import repository, service
from app.modules.drivers.schemas import (
    DriverDetail, DriverIn, DriverOut, DriverPage, DriverPatch, VerificationSent, VerifyIn, VerifyOut,
)

router = APIRouter(prefix="/drivers", tags=["drivers"])
read = require("drivers_vehicles", "R")
write = require("drivers_vehicles", "W")
CSV_FIELDS = ["code", "driver_name", "carrier_name", "phone", "whatsapp_number", "preferred_language",
              "whatsapp_opt_in", "verified", "driver_status", "licence_number", "active_shipments", "last_activity"]


@router.get("", response_model=DriverPage)
async def list_drivers(
    q: str | None = None, carrier_id: UUID | None = None, language: str | None = None,
    opt_in: bool | None = None, verified: bool | None = None, sort: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    p: Principal = Depends(read), db: AsyncSession = Depends(get_db),
):
    return await service.page(db, p, (q, carrier_id, language, opt_in, verified), sort, limit, offset)


@router.get("/export.csv")
async def export_drivers(
    q: str | None = None, carrier_id: UUID | None = None, language: str | None = None,
    opt_in: bool | None = None, verified: bool | None = None, sort: str | None = None,
    p: Principal = Depends(read), db: AsyncSession = Depends(get_db),
):
    rows = await service.enrich(db, list(await repository.list_all(db, p, (q, carrier_id, language, opt_in, verified), sort)))
    return csv_response("drivers.csv", CSV_FIELDS, [r.model_dump() for r in rows])


@router.post("/import", response_model=ImportResult)
async def import_drivers(dry_run: bool = True, file: UploadFile = File(...), p: Principal = Depends(write),
                         db: AsyncSession = Depends(get_db)):
    result = await service.import_csv(db, p, file, dry_run)
    if not dry_run and not result.errors:
        await db.commit()
    return result


@router.post("", response_model=DriverOut, status_code=201)
async def create_driver(body: DriverIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    d = await service.create(db, p, body)
    await db.commit()
    return (await service.enrich(db, [d]))[0]


@router.get("/{driver_id}", response_model=DriverDetail)
async def get_driver(driver_id: UUID, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.detail(db, p, driver_id)


@router.patch("/{driver_id}", response_model=DriverOut)
async def update_driver(driver_id: UUID, body: DriverPatch, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    d = await service.update(db, p, driver_id, body)
    await db.commit()
    return (await service.enrich(db, [d]))[0]


@router.delete("/{driver_id}", response_model=DriverOut)
async def deactivate_driver(driver_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    d = await service.deactivate(db, p, driver_id)
    await db.commit()
    return (await service.enrich(db, [d]))[0]


@router.post("/{driver_id}/whatsapp/verification", response_model=VerificationSent)
async def request_verification(driver_id: UUID, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    redis = get_redis()
    try:
        out = await service.request_verification(db, p, driver_id, redis)
    finally:
        await redis.aclose()
    await db.commit()
    return out


@router.post("/{driver_id}/whatsapp/verify", response_model=VerifyOut)
async def verify(driver_id: UUID, body: VerifyIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    await service.verify(db, p, driver_id, body.code)
    await db.commit()
    return VerifyOut(verified=True)
