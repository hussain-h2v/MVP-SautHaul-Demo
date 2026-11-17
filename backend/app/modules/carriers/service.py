from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.auth.deps import Principal
from app.modules.carriers import repository
from app.modules.carriers.models import Carrier
from app.modules.carriers.schemas import CarrierDetail, CarrierIn, CarrierOut, CarrierPatch
from app.modules.drivers import service as drivers_service
from app.modules.shipments import service as shipments_service
from app.modules.vehicles import service as vehicles_service


async def names(db: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    return await repository.names(db, ids)


async def enrich(db: AsyncSession, rows: list[Carrier]) -> list[CarrierOut]:
    ids = [r.id for r in rows]
    dc = await drivers_service.counts_by_carrier(db, ids)
    vc = await vehicles_service.counts_by_carrier(db, ids)
    return [
        CarrierOut(
            id=r.id, code=r.code, carrier_name=r.carrier_name, contact_email=r.contact_email,
            contact_phone=r.contact_phone, active_flag=r.active_flag,
            allowed_vehicle_type_codes=list(r.allowed_vehicle_type_codes or []),
            driver_count=dc.get(r.id, 0), vehicle_count=vc.get(r.id, 0),
        )
        for r in rows
    ]


async def detail(db: AsyncSession, p: Principal, carrier_id: UUID) -> CarrierDetail:
    c = await repository.get(db, p, carrier_id)
    if c is None:
        raise NotFoundError("Carrier not found")
    base = (await enrich(db, [c]))[0]
    stats = await shipments_service.stats_for_carrier(db, c.id)
    return CarrierDetail(**base.model_dump(), **stats)


async def _check_types(db: AsyncSession, codes: list[str]) -> None:
    unknown = set(codes) - await vehicles_service.known_type_codes(db)
    if unknown:
        raise ValidationAppError(f"Unknown vehicle types: {', '.join(sorted(unknown))}")


async def create(db: AsyncSession, body: CarrierIn) -> Carrier:
    code = body.code.upper()
    if await repository.by_code(db, code):
        raise ConflictError("CODE_EXISTS", f"Carrier code {code} already exists")
    await _check_types(db, body.allowed_vehicle_type_codes)
    c = Carrier(**{**body.model_dump(), "code": code})
    db.add(c)
    try:
        await db.flush()
    except Exception:
        raise ConflictError("DUPLICATE", "A carrier with this name already exists") from None
    return c


async def update(db: AsyncSession, p: Principal, carrier_id: UUID, body: CarrierPatch) -> Carrier:
    c = await repository.get(db, p, carrier_id)
    if c is None:
        raise NotFoundError("Carrier not found")
    data = body.model_dump(exclude_unset=True)
    if "allowed_vehicle_type_codes" in data:
        await _check_types(db, data["allowed_vehicle_type_codes"] or [])
    for k, v in data.items():
        setattr(c, k, v)
    return c
