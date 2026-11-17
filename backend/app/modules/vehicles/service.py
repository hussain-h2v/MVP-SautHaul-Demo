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
