from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.listing import ImportResult, csv_response
from app.modules.auth.deps import Principal, require
from app.modules.facilities import repository, service
from app.modules.facilities.schemas import (
    ContactIn, ContactOut, ContactPatch, FacilityDetail, FacilityIn, FacilityOut, FacilityPage, FacilityPatch,
)

router = APIRouter(prefix="/facilities", tags=["facilities"])
read = require("docks_slots_rules", "R")
write = require("manage_master", "W")


@router.get("", response_model=FacilityPage)
async def list_facilities(
    q: str | None = None, active: bool | None = None, sort: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    p: Principal = Depends(read), db: AsyncSession = Depends(get_db),
):
    total, rows = await repository.list_page(db, p, q, active, sort, limit, offset)
    return FacilityPage(total=total, items=[FacilityOut.model_validate(r) for r in rows])


@router.get("/export.csv")
async def export_facilities(q: str | None = None, active: bool | None = None, sort: str | None = None,
                            p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    rows = await repository.list_all(db, p, q, active, sort)
    return csv_response("facilities.csv", service.CSV_COLUMNS, [FacilityOut.model_validate(r).model_dump() for r in rows])


@router.post("/import", response_model=ImportResult)
async def import_facilities(dry_run: bool = True, file: UploadFile = File(...),
                            _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    result = await service.import_csv(db, file, dry_run)
    if not dry_run:
        await db.commit()
    return result


@router.get("/{facility_id}", response_model=FacilityDetail)
async def get_facility(facility_id: UUID, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.detail(db, p, facility_id)


@router.post("", response_model=FacilityOut, status_code=201)
async def create_facility(body: FacilityIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    f = await service.create(db, body)
    await db.commit()
    return FacilityOut.model_validate(f)


@router.patch("/{facility_id}", response_model=FacilityOut)
async def update_facility(facility_id: UUID, body: FacilityPatch, p: Principal = Depends(write),
                          db: AsyncSession = Depends(get_db)):
    f = await service.update(db, p, facility_id, body)
    await db.commit()
    return FacilityOut.model_validate(f)


@router.post("/{facility_id}/contacts", response_model=ContactOut, status_code=201)
async def add_contact(facility_id: UUID, body: ContactIn, p: Principal = Depends(write),
                      db: AsyncSession = Depends(get_db)):
    c = await service.add_contact(db, p, facility_id, body)
    await db.commit()
    return ContactOut.model_validate(c).model_copy(update={"missing_email": not c.email})


@router.patch("/{facility_id}/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(facility_id: UUID, contact_id: UUID, body: ContactPatch, p: Principal = Depends(write),
                         db: AsyncSession = Depends(get_db)):
    c = await service.update_contact(db, p, facility_id, contact_id, body)
    await db.commit()
    return ContactOut.model_validate(c).model_copy(update={"missing_email": not c.email})


@router.delete("/{facility_id}/contacts/{contact_id}", status_code=204)
async def deactivate_contact(facility_id: UUID, contact_id: UUID, p: Principal = Depends(write),
                             db: AsyncSession = Depends(get_db)) -> None:
    await service.update_contact(db, p, facility_id, contact_id, None)
    await db.commit()
