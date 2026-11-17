"""Pure feasibility rules for dock slots (spec section 5). No database, no AI, no clock: every
input is passed in, so the rules are exhaustively unit-testable.

A slot run (one slot, or consecutive slots on one dock for long unloads) is feasible only if:
 1 it starts at or after the effective ETA (upper bound for a range)
 2 dock type, refrigeration, weight, heavy-load rule and vehicle type are compatible
 3 the run is long enough for expected_unload_min (consecutive slots may be combined)
 4 every slot is OPEN, the dock is ACTIVE and no breakdown / maintenance / capacity-reduction /
   manual-block event overlaps the run
 5 it lies inside operating hours; a start after the last-new-start rule is allowed but flagged
   needs_planner_approval
 6 the truck can finish by the driver's latest acceptable time
 7 no active booking or unexpired hold occupies any slot (passed in as `occupied`)"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.docks.service import compatibility_problems

BLOCKING_EVENTS = frozenset({"BREAKDOWN", "MAINTENANCE", "CAPACITY_REDUCTION", "MANUAL_BLOCK"})
MAX_WINDOWS = 3


@dataclass(frozen=True)
class ShipmentFacts:
    id: object
    facility_id: object
    vehicle_type_code: str | None
    required_dock_type: str
    temperature_control_required: bool
    load_weight_kg: int
    expected_unload_min: int
    priority_code: str


@dataclass(frozen=True)
class DockFacts:
    id: object
    code: str
    dock_type: str
    status: str
    supports_refrigerated: bool
    max_weight_kg: int
    compatible_vehicle_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class SlotFacts:
    id: object
    dock_id: object
    start: datetime
    end: datetime
    status: str


@dataclass(frozen=True)
class EventFacts:
    dock_id: object
    event_type: str
    start: datetime
    end: datetime | None


@dataclass(frozen=True)
class FacilityFacts:
    tz: str
    open_time: time
    close_time: time
    last_start: time | None = None
    heavy_kg: int | None = None


@dataclass
class Option:
    slot_ids: tuple
    dock_id: object
    dock_code: str
    start: datetime
    end: datetime
    needs_planner_approval: bool = False
    reasons: list[str] = field(default_factory=list)
    explanation: str = ""
    rank: int = 0
    wasted_min: int = 0

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def dock_problems(shipment: ShipmentFacts, dock: DockFacts, facility: FacilityFacts) -> list[str]:
    problems = compatibility_problems(
        dock_type=dock.dock_type, dock_status=dock.status, supports_refrigerated=dock.supports_refrigerated,
        max_weight_kg=dock.max_weight_kg, required_dock_type=shipment.required_dock_type,
        temperature_control_required=shipment.temperature_control_required,
        load_weight_kg=shipment.load_weight_kg, heavy_required_kg=facility.heavy_kg)
    if dock.compatible_vehicle_types and shipment.vehicle_type_code \
            and shipment.vehicle_type_code not in dock.compatible_vehicle_types:
        problems.append("VEHICLE_TYPE_NOT_ALLOWED")
    return problems


def _overlaps(a_start: datetime, a_end: datetime, e: EventFacts) -> bool:
    return e.start < a_end and (e.end is None or e.end > a_start)


def run_problems(run: list[SlotFacts], shipment: ShipmentFacts, facility: FacilityFacts, events: list[EventFacts],
                 occupied: set, *, eta: datetime | None, latest_finish: datetime | None) -> list[str]:
    """Why this run of consecutive slots on one dock cannot take the shipment (empty = feasible)."""
    problems: list[str] = []
    start, end = run[0].start, run[-1].end
    if eta is not None and start < eta:
        problems.append("BEFORE_ETA")
    if sum(int((s.end - s.start).total_seconds() // 60) for s in run) < shipment.expected_unload_min:
        problems.append("TOO_SHORT")
    if any(a.end != b.start for a, b in zip(run, run[1:], strict=False)):
        problems.append("NOT_CONSECUTIVE")
    if any(s.status != "OPEN" for s in run):
        problems.append("SLOT_BLOCKED")
    if any(s.id in occupied for s in run):
        problems.append("OCCUPIED")
    if any(_overlaps(start, end, e) for e in events if e.event_type in BLOCKING_EVENTS and e.dock_id == run[0].dock_id):
        problems.append("DOCK_EVENT")
    zone = ZoneInfo(facility.tz)
    ls, le = start.astimezone(zone), end.astimezone(zone)
    if ls.date() != le.date() or ls.time() < facility.open_time or le.time() > facility.close_time:
        problems.append("OUTSIDE_HOURS")
    if latest_finish is not None and start + timedelta(minutes=shipment.expected_unload_min) > latest_finish:
        problems.append("MISSES_DEADLINE")
    return problems


def needs_planner_approval(run: list[SlotFacts], facility: FacilityFacts) -> bool:
    if facility.last_start is None:
        return False
    return run[0].start.astimezone(ZoneInfo(facility.tz)).time() > facility.last_start


def build_options(shipment: ShipmentFacts, facility: FacilityFacts, docks: list[DockFacts], slots: list[SlotFacts],
                  events: list[EventFacts], occupied: set, *, eta: datetime | None,
                  latest_finish: datetime | None = None, max_windows: int = MAX_WINDOWS
                  ) -> tuple[list[Option], Counter]:
    """Every feasible run, unranked, plus a Counter of why candidates were rejected (for escalation hand-off)."""
    rejections: Counter = Counter()
    options: list[Option] = []
    by_dock: dict[object, list[SlotFacts]] = {}
    for s in sorted(slots, key=lambda x: x.start):
        by_dock.setdefault(s.dock_id, []).append(s)
    for dock in docks:
        dock_list = by_dock.get(dock.id, [])
        if not dock_list:
            continue
        bad = dock_problems(shipment, dock, facility)
        if bad:
            for p in bad:
                rejections[p] += len(dock_list)
            continue
        for i, first in enumerate(dock_list):
            run = [first]
            while sum(int((s.end - s.start).total_seconds() // 60) for s in run) < shipment.expected_unload_min \
                    and len(run) < max_windows and i + len(run) < len(dock_list) \
                    and dock_list[i + len(run)].start == run[-1].end:
                run.append(dock_list[i + len(run)])
            problems = run_problems(run, shipment, facility, events, occupied, eta=eta, latest_finish=latest_finish)
            if problems:
                for p in problems:
                    rejections[p] += 1
                continue
            reasons = ["COMPATIBLE_DOCK", "FITS_UNLOAD_WINDOW", "AFTER_ETA"]
            if len(run) > 1:
                reasons.append(f"COMBINES_{len(run)}_WINDOWS")
            if latest_finish is not None:
                reasons.append("MEETS_FINISH_DEADLINE")
            approval = needs_planner_approval(run, facility)
            if approval:
                reasons.append("NEEDS_PLANNER_APPROVAL")
            total = sum(int((s.end - s.start).total_seconds() // 60) for s in run)
            options.append(Option(
                slot_ids=tuple(s.id for s in run), dock_id=dock.id, dock_code=dock.code, start=run[0].start,
                end=run[-1].end, needs_planner_approval=approval, reasons=reasons,
                wasted_min=total - shipment.expected_unload_min))
    return options, rejections
