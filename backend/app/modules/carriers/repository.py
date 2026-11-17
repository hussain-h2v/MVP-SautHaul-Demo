from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import scope_by_carrier
from app.modules.carriers.models import Carrier
from app.modules.auth.deps import Principal


async def list_page(db: AsyncSession, p: Principal, limit: int, offset: int):
    stmt = select(Carrier)
    stmt = scope_by_carrier(stmt, Carrier.id, p)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Carrier.code).limit(limit).offset(offset))).scalars().all()
    return total, rows
