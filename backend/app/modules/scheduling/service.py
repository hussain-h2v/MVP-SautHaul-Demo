"""Scheduling service: read-only. It ranks and explains options but never reserves anything:
showing an option is not reserving it (spec section 5). All writes live in modules/booking."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.booking import readers
from app.modules.eta import service as eta_service
from app.modules.scheduling import feasibility as f
from app.modules.scheduling.feasibility import (
    DockFacts, EventFacts, FacilityFacts, Option, ShipmentFacts, SlotFacts,
)
from app.modules.scheduling.ranking import rank_options
from app.modules.settings import service as settings_service
from app.modules.shipments import service as shipments_service
from app.modules.vehicles import service as vehicles_service

DEFAULT_HORIZON_HOURS = 72


@dataclass
class Context:
    shipment: object
    facts: ShipmentFacts
    facility: FacilityFacts
    facility_id: UUID
    docks: dict
    dock_facts: list[DockFacts]


@dataclass
class OptionsResult:
    options: list[Option]
    total_feasible: int
    rejections: dict[str, int]
    eta: eta_service.EffectiveEta | None
    slots: dict
    docks: dict
    tz: str


@dataclass
class RunCheck:
    problems: list[str]
    needs_planner_approval: bool
    start: datetime | None = None
    end: datetime | None = None


async def load_context(db: AsyncSession, shipment_id: UUID) -> Context:
    s = (await shipments_service.get_many(db, [shipment_id])).get(shipment_id)
    if s is None:
        raise NotFoundError("Shipment not found")
    fac = (await readers.facilities_by_ids(db, [s.destination_facility_id]))[s.destination_facility_id]
    today = datetime.now(ZoneInfo(fac.timezone)).date()
    last = await readers.rule_value(db, fac.id, "LAST_NEW_START_TIME", today)
    heavy = await readers.rule_value(db, fac.id, "HEAVY_DOCK_REQUIRED_KG", today)
    from datetime import time

    facility = FacilityFacts(tz=fac.timezone, open_time=fac.open_time, close_time=fac.close_time,
                             last_start=time.fromisoformat(last) if last else None, heavy_kg=int(heavy) if heavy else None)
    docks = {d.id: d for d in await readers.facility_docks(db, fac.id)}
    dock_facts = [DockFacts(id=d.id, code=d.dock_code, dock_type=d.dock_type, status=d.dock_status,
                            supports_refrigerated=d.supports_refrigerated, max_weight_kg=d.max_vehicle_weight_kg,
                            compatible_vehicle_types=tuple(d.compatible_vehicle_type_codes or ())) for d in docks.values()]
    facts = ShipmentFacts(id=s.id, facility_id=fac.id, vehicle_type_code=await vehicles_service.type_code_for_vehicle(db, s.vehicle_id),
                          required_dock_type=s.required_dock_type, temperature_control_required=s.temperature_control_required,
                          load_weight_kg=s.load_weight_kg, expected_unload_min=s.expected_unload_min, priority_code=s.priority_code)
    return Context(s, facts, facility, fac.id, docks, dock_facts)


async def find_options(db: AsyncSession, shipment_id: UUID, *, effective_eta: datetime | None = None,
                       latest_finish: datetime | None = None, limit: int = 5, now: datetime | None = None,
                       horizon_hours: int = DEFAULT_HORIZON_HOURS) -> OptionsResult:
    now = now or datetime.now(UTC)
    ctx = await load_context(db, shipment_id)
    eta_info = await eta_service.effective_eta(db, shipment_id)
    eta = effective_eta or (eta_info.ts if eta_info else None)
    lo = max(eta, now) if eta else now
    hi = lo + timedelta(hours=horizon_hours)
    slots = await readers.slots_between(db, ctx.facility_id, lo - timedelta(minutes=1), hi)
    slot_map = {s.id: s for s in slots}
    events = await readers.events_overlapping(db, list(ctx.docks), lo, hi + timedelta(hours=24))
    own = await shipments_own_claims(db, shipment_id)
    occupied = await readers.occupied_slot_ids(db, list(slot_map), now, ignore_hold_ids=(), ignore_appointment_ids=())
    occupied |= own
    options, rejections = f.build_options(
        ctx.facts, ctx.facility, ctx.dock_facts,
        [SlotFacts(s.id, s.dock_id, s.slot_start_ts, s.slot_end_ts, s.slot_status) for s in slots],
        [EventFacts(e.dock_id, e.event_type, e.event_start_ts, e.event_end_ts) for e in events],
        occupied, eta=eta, latest_finish=latest_finish)
    ranked = rank_options(options, eta=eta, tz=ZoneInfo(ctx.facility.tz))
    return OptionsResult(ranked[:limit], len(ranked), dict(rejections), eta_info, slot_map, ctx.docks, ctx.facility.tz)


async def shipments_own_claims(db: AsyncSession, shipment_id: UUID) -> set[UUID]:
    """The shipment's own current appointment and hold slots are never offered back to it."""
    from app.modules.appointments import service as appointments_service

    own: set[UUID] = set()
    for a in await appointments_service.for_shipment(db, shipment_id):
        if a.appointment_status in ("PENDING_CONFIRMATION", "CONFIRMED", "IN_PROGRESS"):
            own.add(a.slot_id)
    return own


async def check_run(db: AsyncSession, ctx: Context, slot_ids: list[UUID], now: datetime, *, check_eta: bool = True,
                    ignore_hold_ids: tuple[UUID, ...] = (), ignore_appointment_ids: tuple[UUID, ...] = ()) -> RunCheck:
    """Re-validate one exact option (used at hold time and again at confirmation)."""
    slot_map = await readers.slots_by_ids(db, slot_ids)
    if len(slot_map) != len(set(slot_ids)):
        return RunCheck(["SLOT_NOT_FOUND"], False)
    run = sorted(slot_map.values(), key=lambda s: s.slot_start_ts)
    if len({s.dock_id for s in run}) != 1 or any(s.facility_id != ctx.facility_id for s in run):
        return RunCheck(["WRONG_FACILITY_OR_DOCK"], False)
    dock = ctx.docks.get(run[0].dock_id)
    if dock is None:
        return RunCheck(["SLOT_NOT_FOUND"], False)
    facts = [SlotFacts(s.id, s.dock_id, s.slot_start_ts, s.slot_end_ts, s.slot_status) for s in run]
    events = await readers.events_overlapping(db, [dock.id], facts[0].start, facts[-1].end)
    occupied = await readers.occupied_slot_ids(db, [s.id for s in run], now, ignore_hold_ids, ignore_appointment_ids)
    eta_info = await eta_service.effective_eta(db, ctx.shipment.id) if check_eta else None
    dfacts = next(d for d in ctx.dock_facts if d.id == dock.id)
    problems = f.dock_problems(ctx.facts, dfacts, ctx.facility)
    problems += f.run_problems(facts, ctx.facts, ctx.facility, [EventFacts(e.dock_id, e.event_type, e.event_start_ts, e.event_end_ts) for e in events],
                               occupied, eta=eta_info.ts if eta_info else None, latest_finish=None)
    if now >= facts[-1].end:
        problems.append("IN_THE_PAST")
    return RunCheck(sorted(set(problems)), f.needs_planner_approval(facts, ctx.facility), facts[0].start, facts[-1].end)
