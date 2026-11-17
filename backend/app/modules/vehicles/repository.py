from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.listing import order_by, search
from app.core.scope import scope_by_carrier
from app.modules.auth.deps import Principal
from app.modules.vehicles.models import Vehicle, VehicleType

SORTS = {"code": Vehicle.code, "registration_number": Vehicle.registration_number, "capacity_kg": Vehicle.capacity_kg}


def _query(p: Principal, q, active, type_code, sort) -> Select:
    stmt = scope_by_carrier(
        select(Vehicle, VehicleType).join(VehicleType, VehicleType.id == Vehicle.vehicle_type_id), Vehicle.carrier_id, p)
    if (cond := search(q, Vehicle.code, Vehicle.registration_number)) is not None:
        stmt = stmt.where(cond)
    if active is not None:
        stmt = stmt.where(Vehicle.active_flag == active)
    if type_code:
        stmt = stmt.where(VehicleType.code == type_code)
    return stmt.order_by(order_by(sort, SORTS, Vehicle.code))


async def list_page(db: AsyncSession, p: Principal, filters: tuple, sort, limit: int, offset: int):
    stmt = _query(p, *filters, sort)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    return total, (await db.execute(stmt.limit(limit).offset(offset))).all()


async def list_all(db: AsyncSession, p: Principal, filters: tuple, sort):
    return (await db.execute(_query(p, *filters, sort))).all()


async def get(db: AsyncSession, p: Principal, vehicle_id: UUID):
    stmt = scope_by_carrier(
        select(Vehicle, VehicleType).join(VehicleType, VehicleType.id == Vehicle.vehicle_type_id)
        .where(Vehicle.id == vehicle_id), Vehicle.carrier_id, p)
    return (await db.execute(stmt)).first()


async def type_by_code(db: AsyncSession, code: str) -> VehicleType | None:
    return (await db.execute(select(VehicleType).where(VehicleType.code == code))).scalar_one_or_none()


async def by_registration(db: AsyncSession, reg: str) -> Vehicle | None:
    return (await db.execute(select(Vehicle).where(Vehicle.registration_number == reg))).scalar_one_or_none()


async def next_code(db: AsyncSession) -> str:
    from sqlalchemy import Integer, cast

    n = (await db.execute(select(func.max(cast(func.substr(Vehicle.code, 4), Integer))).where(
        Vehicle.code.op("~")("^VEH[0-9]+$")))).scalar()
    return f"VEH{(n or 0) + 1:03d}"
