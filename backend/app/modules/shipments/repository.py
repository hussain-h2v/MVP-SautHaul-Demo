from uuid import UUID

from sqlalchemy import Integer, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.listing import order_by, search
from app.core.scope import scope_by_carrier, scope_by_facility
from app.modules.auth.deps import Principal
from app.modules.shipments.models import Shipment

SORTS = {
    "code": Shipment.code, "priority_code": Shipment.priority_code, "requested_date": Shipment.requested_date,
    "expected_unload_min": Shipment.expected_unload_min, "current_status": Shipment.current_status,
}
ACTIVE = ("ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK")


def scoped(stmt: Select, p: Principal) -> Select:
    """Every shipment read goes through here: planners see their facilities, carrier users see their own
    carrier's shipments that have actually been offered (never drafts)."""
    if p.role == "facility_planner":
        return scope_by_facility(stmt, Shipment.destination_facility_id, p)
    if p.role == "carrier_user":
        return scope_by_carrier(stmt, Shipment.carrier_id, p).where(Shipment.offer_status != "draft")
    return scope_by_carrier(scope_by_facility(stmt, Shipment.destination_facility_id, p), Shipment.carrier_id, p)


def _query(p: Principal, f: dict, sort: str | None) -> Select:
    stmt = scoped(select(Shipment), p)
    if (cond := search(f.get("q"), Shipment.code, Shipment.order_reference, Shipment.customer_name,
                       Shipment.origin_city)) is not None:
        stmt = stmt.where(cond)
    for key, col in (("status", Shipment.current_status), ("priority", Shipment.priority_code),
                     ("facility_id", Shipment.destination_facility_id), ("carrier_id", Shipment.carrier_id),
                     ("offer_status", Shipment.offer_status)):
        if f.get(key) is not None:
            stmt = stmt.where(col == f[key])
    return stmt.order_by(order_by(sort, SORTS, Shipment.code))


async def list_page(db: AsyncSession, p: Principal, filters: dict, sort, limit: int, offset: int):
    stmt = _query(p, filters, sort)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    return total, (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()


async def list_all(db: AsyncSession, p: Principal, filters: dict, sort):
    return (await db.execute(_query(p, filters, sort))).scalars().all()


async def get(db: AsyncSession, p: Principal, shipment_id: UUID) -> Shipment | None:
    return (await db.execute(scoped(select(Shipment).where(Shipment.id == shipment_id), p))).scalar_one_or_none()


async def by_order_reference(db: AsyncSession, ref: str) -> Shipment | None:
    return (await db.execute(select(Shipment).where(Shipment.order_reference == ref))).scalar_one_or_none()


async def next_code(db: AsyncSession) -> str:
    n = (await db.execute(select(func.max(cast(func.substr(Shipment.code, 4), Integer))).where(
        Shipment.code.op("~")("^SHP[0-9]+$")))).scalar()
    return f"SHP{(n or 1000) + 1}"


async def stats_for_carrier(db: AsyncSession, carrier_id: UUID) -> dict[str, int]:
    rows = await db.execute(select(Shipment.current_status, func.count()).where(
        Shipment.carrier_id == carrier_id, Shipment.offer_status != "draft").group_by(Shipment.current_status))
    by = dict(rows.all())
    return {
        "shipments_total": sum(by.values()),
        "shipments_active": sum(n for s, n in by.items() if s not in ("COMPLETED", "CANCELLED")),
        "shipments_completed": by.get("COMPLETED", 0),
        "shipments_cancelled": by.get("CANCELLED", 0),
    }


async def active_counts_by_driver(db: AsyncSession, ids: list[UUID]) -> dict[UUID, int]:
    rows = await db.execute(select(Shipment.driver_id, func.count()).where(
        Shipment.driver_id.in_(ids), Shipment.current_status.in_(ACTIVE)).group_by(Shipment.driver_id))
    return {d: n for d, n in rows.all()}


async def get_many(db: AsyncSession, ids: list[UUID]) -> dict[UUID, Shipment]:
    if not ids:
        return {}
    rows = (await db.execute(select(Shipment).where(Shipment.id.in_(ids)))).scalars().all()
    return {s.id: s for s in rows}


async def inbound_for_facility(db: AsyncSession, facility_id: UUID) -> list[Shipment]:
    """Trucks on the way: assigned to a driver, not finished or cancelled."""
    return list((await db.execute(select(Shipment).where(
        Shipment.destination_facility_id == facility_id, Shipment.driver_id.is_not(None),
        Shipment.current_status.notin_(("COMPLETED", "CANCELLED"))).order_by(Shipment.code))).scalars().all())


async def active_counts_by_vehicle(db: AsyncSession, ids: list[UUID]) -> dict[UUID, int]:
    if not ids:
        return {}
    rows = await db.execute(select(Shipment.vehicle_id, func.count()).where(
        Shipment.vehicle_id.in_(ids), Shipment.current_status.in_(ACTIVE)).group_by(Shipment.vehicle_id))
    return {v: n for v, n in rows.all()}


async def history_for_driver(db: AsyncSession, driver_id: UUID, limit: int = 20):
    rows = await db.execute(select(Shipment).where(Shipment.driver_id == driver_id)
                            .order_by(Shipment.original_eta_ts.desc()).limit(limit))
    return rows.scalars().all()
