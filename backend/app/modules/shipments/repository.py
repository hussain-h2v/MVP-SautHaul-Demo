from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import scope_by_carrier, scope_by_facility
from app.modules.shipments.models import Shipment
from app.modules.auth.deps import Principal


async def list_page(db: AsyncSession, p: Principal, limit: int, offset: int):
    stmt = select(Shipment)
    stmt = scope_by_carrier(stmt, Shipment.carrier_id, p)
    stmt = scope_by_facility(stmt, Shipment.destination_facility_id, p) if p.role == 'facility_planner' else stmt
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Shipment.code).limit(limit).offset(offset))).scalars().all()
    return total, rows
