from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vehicles.models import Vehicle, VehicleType


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
