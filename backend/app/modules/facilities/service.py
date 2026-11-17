from datetime import time
from uuid import UUID

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.listing import ImportError_, ImportResult, read_csv
from app.modules.auth.deps import Principal
from app.modules.docks import service as docks_service
from app.modules.facilities import repository
from app.modules.facilities.models import Facility, FacilityContact
from app.modules.facilities.schemas import (
    ContactIn, ContactOut, ContactPatch, FacilityDetail, FacilityIn, FacilityOut, FacilityPatch,
)

CSV_COLUMNS = ["code", "facility_name", "address", "city", "state", "timezone", "open_time", "close_time",
               "checkin_grace_min", "default_unload_min", "notes"]


async def detail(db: AsyncSession, p: Principal, facility_id: UUID) -> FacilityDetail:
    f = await repository.get(db, p, facility_id)
    if f is None:
        raise NotFoundError("Facility not found")
    contacts = [ContactOut.model_validate(c).model_copy(update={"missing_email": not c.email})
                for c in await repository.contacts(db, f.id)]
    return FacilityDetail(**FacilityOut.model_validate(f).model_dump(), contacts=contacts,
                          dock_count=await docks_service.count_for_facility(db, f.id))


async def create(db: AsyncSession, body: FacilityIn) -> Facility:
    code = body.code.upper()
    if await repository.by_code(db, code):
        raise ConflictError("CODE_EXISTS", f"Facility code {code} already exists")
    f = Facility(**{**body.model_dump(), "code": code})
    db.add(f)
    try:
        await db.flush()
    except Exception:
        raise ConflictError("DUPLICATE", "A facility with this name already exists") from None
    return f


async def update(db: AsyncSession, p: Principal, facility_id: UUID, body: FacilityPatch) -> Facility:
    f = await repository.get(db, p, facility_id)
    if f is None:
        raise NotFoundError("Facility not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(f, k, v)
    if f.close_time <= f.open_time:
        raise ValidationAppError("close_time must be after open_time")
    return f


async def add_contact(db: AsyncSession, p: Principal, facility_id: UUID, body: ContactIn) -> FacilityContact:
    f = await repository.get(db, p, facility_id)
    if f is None:
        raise NotFoundError("Facility not found")
    c = FacilityContact(facility_id=f.id, **body.model_dump())
    db.add(c)
    await db.flush()
    return c


async def update_contact(db: AsyncSession, p: Principal, facility_id: UUID, contact_id: UUID,
                         body: ContactPatch | None) -> FacilityContact:
    if await repository.get(db, p, facility_id) is None:
        raise NotFoundError("Facility not found")
    c = await repository.get_contact(db, facility_id, contact_id)
    if c is None:
        raise NotFoundError("Contact not found")
    if body is None:
        c.active_flag = False
    else:
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(c, k, v)
    return c


async def import_csv(db: AsyncSession, file: UploadFile, dry_run: bool) -> ImportResult:
    rows = await read_csv(file, ["code", "facility_name", "city", "state", "open_time", "close_time"])
    errors: list[ImportError_] = []
    created, seen = 0, set()
    for n, row in rows:
        try:
            body = FacilityIn(
                code=row["code"], facility_name=row["facility_name"], address=row.get("address") or None,
                city=row["city"], state=row["state"], timezone=row.get("timezone") or "Asia/Kolkata",
                open_time=time.fromisoformat(row["open_time"]), close_time=time.fromisoformat(row["close_time"]),
                checkin_grace_min=int(row.get("checkin_grace_min") or 30),
                default_unload_min=int(row.get("default_unload_min") or 60), notes=row.get("notes") or None,
            )
            code = body.code.upper()
            if code in seen or await repository.by_code(db, code):
                raise ValueError(f"Facility code {code} already exists")
            seen.add(code)
            if not dry_run:
                db.add(Facility(**{**body.model_dump(), "code": code}))
            created += 1
        except (ValidationError, ValueError) as e:
            msg = "; ".join(x["msg"] for x in e.errors()) if isinstance(e, ValidationError) else str(e)
            errors.append(ImportError_(row=n, message=msg))
    if errors and not dry_run:
        await db.rollback()
        return ImportResult(dry_run=False, created=0, errors=errors)
    return ImportResult(dry_run=dry_run, created=created, errors=errors)


async def summaries(db: AsyncSession, ids: list[UUID]) -> dict[UUID, tuple[str, str]]:
    return await repository.summaries(db, ids)


async def id_by_code(db: AsyncSession, code: str) -> tuple[UUID, time, str] | None:
    f = await repository.by_code(db, code.upper())
    return (f.id, f.open_time, f.timezone) if f and f.active_flag else None
