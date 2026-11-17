from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.outbox import emit
from app.modules.booking.models import Escalation
from app.modules.coordinator.inbox_schemas import EscalationOut
from app.modules.drivers import service as drivers_service
from app.modules.shipments import service as shipments_service
from app.modules.users import service as users_service


async def _out(db: AsyncSession, rows: list[Escalation]) -> list[EscalationOut]:
    from app.modules.carriers import service as carriers_service

    ships = await shipments_service.get_many(db, [e.shipment_id for e in rows if e.shipment_id])
    carriers = await carriers_service.names(db, list({s.carrier_id for s in ships.values() if s.carrier_id}))
    drivers = await drivers_service.get_many(db, [s.driver_id for s in ships.values() if s.driver_id])
    people = await users_service.names(db, [e.assigned_to for e in rows if e.assigned_to])
    out = []
    for e in rows:
        s = ships.get(e.shipment_id)
        d = drivers.get(s.driver_id) if s and s.driver_id else None
        out.append(EscalationOut(
            id=e.id, shipment_id=e.shipment_id, shipment_code=s.code if s else None,
            carrier_name=carriers.get(s.carrier_id) if s and s.carrier_id else None, driver_name=d.driver_name if d else None,
            driver_phone=(d.whatsapp_number or d.phone) if d else None, reason_code=e.reason_code, status=e.status,
            handoff_record=e.handoff_record or {}, assigned_to={"id": str(e.assigned_to), "name": people.get(e.assigned_to, "")} if e.assigned_to else None,
            resolution=e.resolution, created_at=e.created_at, closed_at=e.closed_at))
    return out


async def list_(db: AsyncSession, status: str | None, limit: int) -> list[EscalationOut]:
    stmt = select(Escalation)
    if status:
        stmt = stmt.where(Escalation.status == status)
    rows = (await db.execute(stmt.order_by(Escalation.created_at.desc()).limit(limit))).scalars().all()
    return await _out(db, list(rows))


async def get(db: AsyncSession, escalation_id: UUID) -> Escalation:
    e = await db.get(Escalation, escalation_id)
    if e is None:
        raise NotFoundError("Escalation not found")
    return e


async def one(db: AsyncSession, escalation_id: UUID) -> EscalationOut:
    return (await _out(db, [await get(db, escalation_id)]))[0]


def _open(e: Escalation) -> None:
    if e.status == "resolved":
        raise ConflictError("ALREADY_RESOLVED", "This escalation is already resolved")


async def assign(db: AsyncSession, escalation_id: UUID, user_id: UUID) -> EscalationOut:
    e = await get(db, escalation_id)
    _open(e)
    e.assigned_to = user_id
    if e.status == "open":
        e.status = "in_progress"
    return (await _out(db, [e]))[0]


async def set_status(db: AsyncSession, escalation_id: UUID, status: str, user_id: UUID) -> EscalationOut:
    if status != "in_progress":
        raise ValidationAppError("Use resolve to close an escalation; status can only be set to in_progress")
    e = await get(db, escalation_id)
    _open(e)
    e.status = "in_progress"
    e.assigned_to = e.assigned_to or user_id
    return (await _out(db, [e]))[0]


async def resolve(db: AsyncSession, escalation_id: UUID, resolution: str, user_id: UUID) -> EscalationOut:
    e = await get(db, escalation_id)
    _open(e)
    e.status, e.resolution, e.closed_at = "resolved", resolution.strip(), datetime.now(UTC)
    e.assigned_to = e.assigned_to or user_id
    emit(db, "escalation.resolved", {"escalation_id": e.id, "shipment_id": e.shipment_id})
    return (await _out(db, [e]))[0]
