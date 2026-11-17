from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.appointments import service as appointments_service
from app.modules.auth.deps import Principal
from app.modules.docks import repository
from app.modules.docks.models import Dock, DockStatusEvent
from app.modules.docks.schemas import (
    AffectedAppointment, DockEventCreated, DockEventIn, DockEventOut, DockIn, DockPatch,
)
from app.modules.shipments import service as shipments_service
from app.modules.slots import service as slots_service
from app.modules.vehicles import service as vehicles_service


async def count_for_facility(db: AsyncSession, facility_id: UUID) -> int:
    return (await db.execute(select(func.count()).select_from(Dock).where(Dock.facility_id == facility_id))).scalar_one()


async def get_in_scope(db: AsyncSession, p: Principal, dock_id: UUID) -> Dock:
    d = await repository.get_dock(db, p, dock_id)
    if d is None:
        raise NotFoundError("Dock not found")
    return d


async def by_ids(db: AsyncSession, ids: list[UUID]) -> dict[UUID, Dock]:
    return await repository.docks_by_ids(db, ids)


async def list_docks(db: AsyncSession, p: Principal, facility_id: UUID | None, status: str | None):
    return await repository.list_docks(db, p, facility_id, status)


async def _check_types(db: AsyncSession, codes: list[str]) -> None:
    unknown = set(codes) - await vehicles_service.known_type_codes(db)
    if unknown:
        raise ValidationAppError(f"Unknown vehicle types: {', '.join(sorted(unknown))}")


async def create_dock(db: AsyncSession, p: Principal, body: DockIn) -> Dock:
    from app.modules.facilities import service as facilities_service  # cycle: facilities.service counts docks

    fac = await facilities_service.get_in_scope(db, p, body.facility_id)
    if await repository.by_facility_code(db, fac.id, body.dock_code.upper()):
        raise ConflictError("DOCK_EXISTS", f"Dock {body.dock_code.upper()} already exists in this facility")
    await _check_types(db, body.compatible_vehicle_type_codes)
    data = body.model_dump()
    data["dock_code"] = body.dock_code.upper()
    d = Dock(code=f"{fac.code}-{data['dock_code']}"[:32], **data)
    db.add(d)
    await db.flush()
    return d


async def update_dock(db: AsyncSession, p: Principal, dock_id: UUID, body: DockPatch) -> Dock:
    d = await get_in_scope(db, p, dock_id)
    data = body.model_dump(exclude_unset=True)
    if "compatible_vehicle_type_codes" in data:
        await _check_types(db, data["compatible_vehicle_type_codes"] or [])
    for k, v in data.items():
        setattr(d, k, v)
    if d.dock_type == "REEFER":
        d.supports_refrigerated = True
    return d


async def retire_dock(db: AsyncSession, p: Principal, dock_id: UUID) -> Dock:
    d = await get_in_scope(db, p, dock_id)
    now = datetime.now(UTC)
    future = await slots_service.future_slot_ids(db, d.id, now)
    if await appointments_service.active_for_slots(db, future):
        raise ConflictError("FUTURE_BOOKINGS", "This dock still has upcoming bookings; move or cancel them first")
    await slots_service.close_slots(db, future, "Dock retired")
    d.dock_status = "INACTIVE"
    return d


async def affected_for_window(db: AsyncSession, dock_id: UUID, start: datetime,
                              end: datetime | None) -> list[AffectedAppointment]:
    slot_ids = await slots_service.slot_ids_in_window(db, dock_id, start, end)
    return await affected_for_slots(db, slot_ids)


async def affected_for_slots(db: AsyncSession, slot_ids: list[UUID]) -> list[AffectedAppointment]:
    appts = await appointments_service.active_for_slots(db, slot_ids)
    if not appts:
        return []
    windows = await slots_service.windows(db, [a.slot_id for a in appts])
    ships = await shipments_service.summaries(db, [a.shipment_id for a in appts])
    return [
        AffectedAppointment(
            appointment_id=a.id, appointment_code=a.code, shipment_code=ships.get(a.shipment_id, {}).get("code"),
            slot_code=windows[a.slot_id][0], slot_start_ts=windows[a.slot_id][1], appointment_status=a.appointment_status,
        )
        for a in sorted(appts, key=lambda x: windows[x.slot_id][1])
    ]


def _event_out(e: DockStatusEvent, dock_code: str, now: datetime, affected: int) -> DockEventOut:
    return DockEventOut(
        id=e.id, dock_id=e.dock_id, dock_code=dock_code, event_type=e.event_type, event_start_ts=e.event_start_ts,
        event_end_ts=e.event_end_ts, reason=e.reason, resolved=e.event_end_ts is not None and e.event_end_ts <= now,
        affected_count=affected,
    )


async def list_events(db: AsyncSession, p: Principal, facility_id: UUID | None, date_from: datetime | None,
                      date_to: datetime | None, open_only: bool) -> list[DockEventOut]:
    docks = {d.id: d for d in await repository.list_docks(db, p, facility_id, None)}
    now = datetime.now(UTC)
    events = await repository.events_for(db, list(docks), date_from, date_to, open_only, now)
    out = []
    for e in events:
        affected = len(await affected_for_window(db, e.dock_id, e.event_start_ts, e.event_end_ts))
        out.append(_event_out(e, docks[e.dock_id].dock_code, now, affected))
    return out


async def create_event(db: AsyncSession, p: Principal, body: DockEventIn) -> tuple[DockStatusEvent, Dock, list]:
    dock = await get_in_scope(db, p, body.dock_id)
    e = DockStatusEvent(dock_id=dock.id, event_type=body.event_type, event_start_ts=body.event_start_ts,
                        event_end_ts=body.event_end_ts, reason=body.reason)
    db.add(e)
    await db.flush()
    affected = []
    if body.event_type != "REOPENED":
        affected = await affected_for_window(db, dock.id, body.event_start_ts, body.event_end_ts)
    return e, dock, affected


def created_out(e: DockStatusEvent, dock: Dock, affected: list[AffectedAppointment]) -> DockEventCreated:
    base = _event_out(e, dock.dock_code, datetime.now(UTC), len(affected))
    return DockEventCreated(**base.model_dump(), affected_appointments=affected)


async def resolve_event(db: AsyncSession, p: Principal, event_id: UUID) -> tuple[DockStatusEvent, Dock]:
    e = await repository.get_event(db, event_id)
    if e is None:
        raise NotFoundError("Event not found")
    dock = await get_in_scope(db, p, e.dock_id)
    now = datetime.now(UTC)
    if e.event_end_ts is not None and e.event_end_ts <= now:
        raise ConflictError("ALREADY_RESOLVED", "This event is already resolved")
    e.event_end_ts = now if now > e.event_start_ts else e.event_start_ts + timedelta(minutes=1)
    return e, dock


def compatibility_problems(*, dock_type: str, dock_status: str, supports_refrigerated: bool, max_weight_kg: int,
                           required_dock_type: str, temperature_control_required: bool, load_weight_kg: int,
                           heavy_required_kg: int | None = None) -> list[str]:
    """Pure dock/load compatibility check (spec section 5, rule 2). Empty list = compatible.
    Shared by yard dock assignment (M3) and the scheduling service (M4)."""
    problems: list[str] = []
    if dock_status != "ACTIVE":
        problems.append("DOCK_NOT_ACTIVE")
    if required_dock_type in ("REEFER", "HEAVY", "STANDARD") and dock_type != required_dock_type:
        problems.append(f"NEEDS_{required_dock_type}_DOCK")
    if temperature_control_required and not (dock_type == "REEFER" or supports_refrigerated):
        problems.append("NEEDS_REFRIGERATED_DOCK")
    if load_weight_kg > max_weight_kg:
        problems.append("LOAD_EXCEEDS_DOCK_LIMIT")
    if heavy_required_kg and load_weight_kg >= heavy_required_kg and dock_type != "HEAVY":
        problems.append("NEEDS_HEAVY_DOCK")
    return problems


async def events_between(db: AsyncSession, dock_ids: list[UUID], start: datetime, end: datetime):
    return await repository.events_for(db, dock_ids, start, end, False, datetime.now(UTC))
