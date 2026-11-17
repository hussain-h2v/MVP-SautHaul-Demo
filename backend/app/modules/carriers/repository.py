from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.listing import order_by, search
from app.core.scope import scope_by_carrier
from app.modules.auth.deps import Principal
from app.modules.carriers.models import Carrier

SORTS = {"code": Carrier.code, "carrier_name": Carrier.carrier_name}


def _query(p: Principal, q, active, sort) -> Select:
    stmt = scope_by_carrier(select(Carrier), Carrier.id, p)
    if (cond := search(q, Carrier.code, Carrier.carrier_name, Carrier.contact_email)) is not None:
        stmt = stmt.where(cond)
    if active is not None:
        stmt = stmt.where(Carrier.active_flag == active)
    return stmt.order_by(order_by(sort, SORTS, Carrier.code))


async def list_page(db: AsyncSession, p: Principal, q, active, sort, limit, offset):
    stmt = _query(p, q, active, sort)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    return total, (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()


async def list_all(db: AsyncSession, p: Principal, q, active, sort):
    return (await db.execute(_query(p, q, active, sort))).scalars().all()


async def get(db: AsyncSession, p: Principal, carrier_id: UUID) -> Carrier | None:
    stmt = scope_by_carrier(select(Carrier).where(Carrier.id == carrier_id), Carrier.id, p)
    return (await db.execute(stmt)).scalar_one_or_none()


async def by_code(db: AsyncSession, code: str) -> Carrier | None:
    return (await db.execute(select(Carrier).where(Carrier.code == code))).scalar_one_or_none()


async def names(db: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    rows = await db.execute(select(Carrier.id, Carrier.carrier_name).where(Carrier.id.in_(ids)))
    return {i: n for i, n in rows.all()}
