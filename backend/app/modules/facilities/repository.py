from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.listing import order_by, search
from app.core.scope import scope_by_facility
from app.modules.auth.deps import Principal
from app.modules.facilities.models import Facility, FacilityContact

SORTS = {"code": Facility.code, "facility_name": Facility.facility_name, "city": Facility.city}


def _query(p: Principal, q: str | None, active: bool | None, sort: str | None) -> Select:
    stmt = scope_by_facility(select(Facility), Facility.id, p)
    if (cond := search(q, Facility.code, Facility.facility_name, Facility.city, Facility.state)) is not None:
        stmt = stmt.where(cond)
    if active is not None:
        stmt = stmt.where(Facility.active_flag == active)
    return stmt.order_by(order_by(sort, SORTS, Facility.code))


async def list_page(db: AsyncSession, p: Principal, q, active, sort, limit: int, offset: int):
    stmt = _query(p, q, active, sort)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return total, rows


async def list_all(db: AsyncSession, p: Principal, q, active, sort):
    return (await db.execute(_query(p, q, active, sort))).scalars().all()


async def get(db: AsyncSession, p: Principal, facility_id: UUID) -> Facility | None:
    stmt = scope_by_facility(select(Facility).where(Facility.id == facility_id), Facility.id, p)
    return (await db.execute(stmt)).scalar_one_or_none()


async def by_code(db: AsyncSession, code: str) -> Facility | None:
    return (await db.execute(select(Facility).where(Facility.code == code))).scalar_one_or_none()


async def contacts(db: AsyncSession, facility_id: UUID):
    return (await db.execute(
        select(FacilityContact).where(FacilityContact.facility_id == facility_id).order_by(FacilityContact.contact_name)
    )).scalars().all()


async def get_contact(db: AsyncSession, facility_id: UUID, contact_id: UUID) -> FacilityContact | None:
    return (await db.execute(select(FacilityContact).where(
        FacilityContact.id == contact_id, FacilityContact.facility_id == facility_id))).scalar_one_or_none()


async def summaries(db: AsyncSession, ids: list[UUID]) -> dict[UUID, tuple[str, str]]:
    rows = await db.execute(select(Facility.id, Facility.code, Facility.facility_name).where(Facility.id.in_(ids)))
    return {i: (c, n) for i, c, n in rows.all()}
