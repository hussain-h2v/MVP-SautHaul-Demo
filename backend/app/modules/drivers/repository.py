from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.listing import order_by, search
from app.core.scope import scope_by_carrier
from app.modules.auth.deps import Principal
from app.modules.carriers.models import Carrier
from app.modules.drivers.models import Driver

SORTS = {"code": Driver.code, "driver_name": Driver.driver_name, "carrier_name": Carrier.carrier_name}


def _query(p: Principal, q, carrier_id, language, opt_in, verified, sort) -> Select:
    stmt = scope_by_carrier(select(Driver).join(Carrier, Carrier.id == Driver.carrier_id), Driver.carrier_id, p)
    if (cond := search(q, Driver.code, Driver.driver_name, Driver.phone, Driver.licence_number)) is not None:
        stmt = stmt.where(cond)
    if carrier_id:
        stmt = stmt.where(Driver.carrier_id == carrier_id)
    if language:
        stmt = stmt.where(Driver.preferred_language == language)
    if opt_in is not None:
        stmt = stmt.where(Driver.whatsapp_opt_in == opt_in)
    if verified is not None:
        stmt = stmt.where(Driver.verified_at.is_not(None) if verified else Driver.verified_at.is_(None))
    return stmt.order_by(order_by(sort, SORTS, Driver.code))


async def list_page(db: AsyncSession, p: Principal, filters: tuple, sort, limit, offset):
    stmt = _query(p, *filters, sort)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    return total, (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()


async def list_all(db: AsyncSession, p: Principal, filters: tuple, sort):
    return (await db.execute(_query(p, *filters, sort))).scalars().all()


async def counts_by_carrier(db: AsyncSession, ids: list[UUID]) -> dict[UUID, int]:
    rows = await db.execute(select(Driver.carrier_id, func.count()).where(Driver.carrier_id.in_(ids))
                            .group_by(Driver.carrier_id))
    return {c: n for c, n in rows.all()}


async def names(db: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    rows = await db.execute(select(Driver.id, Driver.driver_name).where(Driver.id.in_(ids)))
    return {i: n for i, n in rows.all()}


async def get(db: AsyncSession, p: Principal, driver_id: UUID) -> Driver | None:
    stmt = scope_by_carrier(select(Driver).where(Driver.id == driver_id), Driver.carrier_id, p)
    return (await db.execute(stmt)).scalar_one_or_none()


async def by_phone(db: AsyncSession, phone: str) -> Driver | None:
    return (await db.execute(select(Driver).where(Driver.phone == phone))).scalar_one_or_none()


async def by_licence(db: AsyncSession, licence: str) -> Driver | None:
    return (await db.execute(select(Driver).where(Driver.licence_number == licence))).scalar_one_or_none()


async def by_whatsapp(db: AsyncSession, number: str) -> Driver | None:
    # Stored numbers may carry separators ("+91-9000010001"); WhatsApp delivers E.164 ("+919000010001"): compare ignoring them.
    from sqlalchemy import func

    clean = func.regexp_replace(Driver.whatsapp_number, r"[^0-9+]", "", "g")
    return (await db.execute(select(Driver).where((Driver.whatsapp_number == number) | (clean == number)).limit(1))).scalar_one_or_none()


async def next_code(db: AsyncSession) -> str:
    from sqlalchemy import Integer, cast

    n = (await db.execute(select(func.max(cast(func.substr(Driver.code, 4), Integer))).where(
        Driver.code.op("~")("^DRV[0-9]+$")))).scalar()
    return f"DRV{(n or 0) + 1:03d}"
