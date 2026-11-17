from uuid import UUID

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.listing import ImportError_, ImportResult, read_csv
from app.modules.auth.deps import Principal
from app.modules.vehicles import repository
from app.modules.vehicles.models import Vehicle, VehicleType
from app.modules.vehicles.schemas import VehicleIn, VehicleOut, VehiclePage, VehiclePatch

CSV_COLUMNS = ["vehicle_type_code", "registration_number", "capacity_kg", "refrigeration_capable", "heavy_capable"]


async def counts_by_carrier(db: AsyncSession, carrier_ids: list[UUID]) -> dict[UUID, int]:
    rows = await db.execute(select(Vehicle.carrier_id, func.count()).where(Vehicle.carrier_id.in_(carrier_ids))
                            .group_by(Vehicle.carrier_id))
    return {cid: n for cid, n in rows.all()}


async def list_types(db: AsyncSession) -> list[VehicleType]:
    return list((await db.execute(select(VehicleType).order_by(VehicleType.code))).scalars().all())


async def known_type_codes(db: AsyncSession) -> set[str]:
    return {t.code for t in await list_types(db)}


async def type_code_for_vehicle(db: AsyncSession, vehicle_id: UUID | None) -> str | None:
    if vehicle_id is None:
        return None
    row = (await db.execute(select(VehicleType.code).join(Vehicle, Vehicle.vehicle_type_id == VehicleType.id)
                            .where(Vehicle.id == vehicle_id))).first()
    return row[0] if row else None


async def get_scoped(db: AsyncSession, p: Principal, vehicle_id: UUID) -> tuple[Vehicle, VehicleType]:
    row = await repository.get(db, p, vehicle_id)
    if row is None:
        raise NotFoundError("Vehicle not found")
    return row[0], row[1]


async def enrich(db: AsyncSession, rows: list[tuple[Vehicle, VehicleType]]) -> list[VehicleOut]:
    from app.modules.carriers import repository as carriers_repo  # import cycle: carriers.service uses this module
    from app.modules.shipments import service as shipments_service

    names = await carriers_repo.names(db, list({v.carrier_id for v, _ in rows}))
    active = await shipments_service.active_counts_by_vehicle(db, [v.id for v, _ in rows])
    return [
        VehicleOut(id=v.id, code=v.code, carrier_id=v.carrier_id, carrier_name=names.get(v.carrier_id, ""),
                   vehicle_type_code=t.code, vehicle_type_description=t.description,
                   registration_number=v.registration_number, capacity_kg=v.capacity_kg,
                   refrigeration_capable=v.refrigeration_capable, heavy_capable=v.heavy_capable,
                   active_flag=v.active_flag, assigned_shipments=active.get(v.id, 0))
        for v, t in rows
    ]


async def page(db: AsyncSession, p: Principal, filters: tuple, sort, limit: int, offset: int) -> VehiclePage:
    total, rows = await repository.list_page(db, p, filters, sort, limit, offset)
    return VehiclePage(total=total, items=await enrich(db, [(r[0], r[1]) for r in rows]))


async def _type(db: AsyncSession, p: Principal, code: str) -> VehicleType:
    from app.modules.carriers import repository as carriers_repo

    t = await repository.type_by_code(db, code)
    if t is None:
        raise ValidationAppError(f"Unknown vehicle type {code}")
    carrier = await carriers_repo.get(db, p, p.carrier_id) if p.carrier_id else None
    allowed = list(carrier.allowed_vehicle_type_codes or []) if carrier else []
    if allowed and code not in allowed:
        raise ValidationAppError(f"Your carrier is not set up for vehicle type {code}", {"allowed": allowed})
    return t


def _carrier(p: Principal) -> UUID:
    if p.carrier_id is None:
        raise ValidationAppError("Only carrier users can manage a carrier's fleet")
    return p.carrier_id


async def create(db: AsyncSession, p: Principal, body: VehicleIn) -> Vehicle:
    carrier_id = _carrier(p)
    t = await _type(db, p, body.vehicle_type_code)
    reg = body.registration_number.upper().strip()
    if await repository.by_registration(db, reg):
        raise ConflictError("REGISTRATION_EXISTS", f"Registration {reg} already exists")
    v = Vehicle(code=await repository.next_code(db), carrier_id=carrier_id, vehicle_type_id=t.id,
                registration_number=reg, capacity_kg=body.capacity_kg,
                refrigeration_capable=body.refrigeration_capable or t.refrigerated_flag,
                heavy_capable=body.heavy_capable or t.typical_dock_type == "HEAVY", active_flag=True)
    db.add(v)
    await db.flush()
    return v


async def update(db: AsyncSession, p: Principal, vehicle_id: UUID, body: VehiclePatch) -> Vehicle:
    v, _ = await get_scoped(db, p, vehicle_id)
    data = body.model_dump(exclude_unset=True)
    if "vehicle_type_code" in data:
        v.vehicle_type_id = (await _type(db, p, data.pop("vehicle_type_code"))).id
    if "registration_number" in data:
        reg = data["registration_number"].upper().strip()
        other = await repository.by_registration(db, reg)
        if other and other.id != v.id:
            raise ConflictError("REGISTRATION_EXISTS", f"Registration {reg} already exists")
        data["registration_number"] = reg
    for k, val in data.items():
        setattr(v, k, val)
    return v


async def retire(db: AsyncSession, p: Principal, vehicle_id: UUID) -> Vehicle:
    from app.modules.shipments import service as shipments_service

    v, _ = await get_scoped(db, p, vehicle_id)
    if (await shipments_service.active_counts_by_vehicle(db, [v.id])).get(v.id):
        raise ConflictError("ACTIVE_SHIPMENTS", "This vehicle is on an active shipment; reassign it first")
    v.active_flag = False
    return v


async def import_csv(db: AsyncSession, p: Principal, file: UploadFile, dry_run: bool) -> ImportResult:
    _carrier(p)
    rows = await read_csv(file, ["vehicle_type_code", "registration_number", "capacity_kg"])
    errors: list[ImportError_] = []
    created, seen = 0, set()
    truthy = ("1", "true", "yes", "y")
    for n, row in rows:
        try:
            body = VehicleIn(vehicle_type_code=row["vehicle_type_code"], registration_number=row["registration_number"],
                             capacity_kg=int(row["capacity_kg"]),
                             refrigeration_capable=row.get("refrigeration_capable", "").lower() in truthy,
                             heavy_capable=row.get("heavy_capable", "").lower() in truthy)
            reg = body.registration_number.upper().strip()
            if reg in seen or await repository.by_registration(db, reg):
                raise ValueError(f"Registration {reg} already exists")
            seen.add(reg)
            await _type(db, p, body.vehicle_type_code)
            if not dry_run:
                await create(db, p, body)
            created += 1
        except ValidationError as e:
            errors.append(ImportError_(row=n, message="; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())))
        except (ValueError, ValidationAppError, ConflictError) as e:
            errors.append(ImportError_(row=n, message=getattr(e, "message", str(e))))
    if errors and not dry_run:
        await db.rollback()
        return ImportResult(dry_run=False, created=0, errors=errors)
    return ImportResult(dry_run=dry_run, created=created, errors=errors)
