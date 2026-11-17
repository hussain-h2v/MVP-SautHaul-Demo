from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import scope_by_facility
from app.modules.facilities.models import Facility
from app.modules.auth.deps import Principal


async def list_page(db: AsyncSession, p: Principal, limit: int, offset: int):
    stmt = select(Facility)
    stmt = scope_by_facility(stmt, Facility.id, p)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Facility.code).limit(limit).offset(offset))).scalars().all()
    return total, rows
