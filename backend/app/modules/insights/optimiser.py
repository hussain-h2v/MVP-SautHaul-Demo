"""Schedule proposal for one facility day: earliest-feasible-start (priority breaks ties) against a first-come-first-served
baseline and against the current plan. PROPOSAL ONLY: this module has no write path. Applying a move is a separate, explicit
action through the booking service (planner "Move to..." on the schedule grid).

Movable = confirmed or pending appointments that have not started and whose truck has not reached the gate. Everything else
(in progress, completed, checked in) is fixed and keeps its slots. A load needs ceil(unload / slot length) consecutive
slots on one compatible dock; blocked slots and slots touched by a dock event are not usable."""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.docks.service import compatibility_problems

PRIORITY_WEIGHT = {"LOW": 1, "NORMAL": 2, "HIGH": 3, "CRITICAL": 4}
PRIORITY_RANK = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}


@dataclass
class Slot:
    id: UUID
    dock_id: UUID
    dock: str
    start: datetime
    end: datetime
    usable: bool


@dataclass
class Dock:
    id: UUID
    code: str
    type: str
    refrigerated: bool
    max_kg: int
    status: str
    slots: list[Slot] = field(default_factory=list)


@dataclass
class Item:
    shipment_id: UUID
    code: str
    priority: str
    required_dock_type: str
    temp: bool
    weight: int
    unload_min: int
    eta: datetime
    booked_at: datetime
    cur_dock: str
    cur_start: datetime
    cur_slot_id: UUID
    carrier: str | None = None


def _needs(item: Item, slot_min: int) -> int:
    return max(1, math.ceil(item.unload_min / slot_min))


def _compatible(item: Item, d: Dock) -> bool:
    return not compatibility_problems(dock_type=d.type, dock_status=d.status, supports_refrigerated=d.refrigerated, max_weight_kg=d.max_kg,
                                      required_dock_type=item.required_dock_type, temperature_control_required=item.temp, load_weight_kg=item.weight)


def earliest_run(item: Item, docks: list[Dock], taken: set[UUID], slot_min: int) -> tuple[Dock, list[Slot]] | None:
    """Earliest start (ties: lower dock code) of `need` consecutive free usable slots on one compatible dock, not before the ETA."""
    need = _needs(item, slot_min)
    best: tuple[datetime, str, Dock, list[Slot]] | None = None
    for d in docks:
        if not _compatible(item, d):
            continue
        s = d.slots
        for i in range(len(s) - need + 1):
            run = s[i:i + need]
            if run[0].start < item.eta:
                continue
            if any((not x.usable) or x.id in taken for x in run):
                continue
            if any(run[j].end != run[j + 1].start for j in range(need - 1)):
                continue
            if best is None or (run[0].start, d.code) < (best[0], best[1]):
                best = (run[0].start, d.code, d, run)
            break  # slots are in time order: the first fit on this dock is its earliest
    return (best[2], best[3]) if best else None


def schedule(items: list[Item], docks: list[Dock], fixed_taken: set[UUID], slot_min: int, strategy: str) -> dict[UUID, tuple[Dock, list[Slot]]]:
    """strategy 'fcfs': in booking order, each takes its earliest feasible run. 'proposed': repeatedly place the load that can
    start soonest; ties go to higher priority, then earlier ETA."""
    taken, out = set(fixed_taken), {}
    if strategy == "fcfs":
        for it in sorted(items, key=lambda i: (i.booked_at, i.code)):
            r = earliest_run(it, docks, taken, slot_min)
            if r:
                out[it.shipment_id] = r
                taken |= {s.id for s in r[1]}
        return out
    pending = list(items)
    while pending:
        cands = []
        for it in pending:
            r = earliest_run(it, docks, taken, slot_min)
            if r:
                cands.append(((r[1][0].start, PRIORITY_RANK[it.priority], it.eta, it.code), it, r))
        if not cands:
            break
        _, it, r = min(cands, key=lambda c: c[0])
        out[it.shipment_id] = r
        taken |= {s.id for s in r[1]}
        pending.remove(it)
    return out


def _wait(it: Item, start: datetime | None) -> int | None:
    return None if start is None else max(0, int((start - it.eta).total_seconds() // 60))


def scorecard(items: list[Item], starts: dict[UUID, datetime | None], placed_docks: dict[UUID, str | None], current: bool = False) -> dict[str, Any]:
    waits = {i.shipment_id: _wait(i, starts.get(i.shipment_id)) for i in items}
    done = [(i, w) for i in items if (w := waits[i.shipment_id]) is not None]
    total = sum(w for _, w in done)
    return {"placed": len(done), "unplaced": len(items) - len(done), "total_wait_min": total, "avg_wait_min": round(total / len(done), 1) if done else 0.0,
            "max_wait_min": max((w for _, w in done), default=0), "priority_weighted_wait": sum(w * PRIORITY_WEIGHT[i.priority] for i, w in done),
            "high_priority_wait_min": sum(w for i, w in done if i.priority in ("HIGH", "CRITICAL")),
            "moved": 0 if current else sum(1 for i in items if starts.get(i.shipment_id) and (starts[i.shipment_id] != i.cur_start or placed_docks.get(i.shipment_id) != i.cur_dock))}


async def _load(db: AsyncSession, facility_id: UUID, start: datetime, end: datetime, now: datetime):
    docks_rows = (await db.execute(text("SELECT id, dock_code, dock_type, supports_refrigerated, max_vehicle_weight_kg, dock_status FROM docks WHERE facility_id = :f ORDER BY dock_code"), {"f": facility_id})).all()
    docks = {r.id: Dock(r.id, r.dock_code, r.dock_type, r.supports_refrigerated, r.max_vehicle_weight_kg, r.dock_status) for r in docks_rows}
    slot_rows = (await db.execute(text("SELECT id, dock_id, slot_start_ts, slot_end_ts, slot_status FROM appointment_slots WHERE facility_id = :f AND slot_start_ts >= :s AND slot_start_ts < :e ORDER BY slot_start_ts"),
                                  {"f": facility_id, "s": start, "e": end})).all()
    events = (await db.execute(text("""SELECT de.dock_id, de.event_start_ts, de.event_end_ts FROM dock_status_events de JOIN docks d ON d.id = de.dock_id
        WHERE d.facility_id = :f AND de.event_type <> 'REOPENED' AND de.event_start_ts < :e AND coalesce(de.event_end_ts, 'infinity'::timestamptz) > :s"""), {"f": facility_id, "s": start, "e": end})).all()
    for r in slot_rows:
        hit = any(ev.dock_id == r.dock_id and ev.event_start_ts < r.slot_end_ts and (ev.event_end_ts is None or ev.event_end_ts > r.slot_start_ts) for ev in events)
        docks[r.dock_id].slots.append(Slot(r.id, r.dock_id, docks[r.dock_id].code, r.slot_start_ts, r.slot_end_ts, r.slot_status == "OPEN" and not hit))
    appts = (await db.execute(text("""SELECT a.id AS appt_id, a.appointment_status, a.booked_at, sl.id AS slot_id, sl.dock_id, sl.slot_start_ts,
          sh.id AS shipment_id, sh.code, sh.priority_code, sh.required_dock_type, sh.temperature_control_required, sh.load_weight_kg, sh.expected_unload_min,
          sh.original_eta_ts, car.carrier_name, ck.gate_in_ts,
          (SELECT eu.declared_eta_ts FROM eta_updates eu WHERE eu.shipment_id = sh.id ORDER BY eu.created_at DESC, eu.id DESC LIMIT 1) AS declared_eta
        FROM appointments a JOIN appointment_slots sl ON sl.id = a.slot_id JOIN shipments sh ON sh.id = a.shipment_id
        LEFT JOIN carriers car ON car.id = sh.carrier_id LEFT JOIN facility_checkins ck ON ck.shipment_id = sh.id
        WHERE a.is_current AND a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS','COMPLETED')
          AND sl.facility_id = :f AND sl.slot_start_ts >= :s AND sl.slot_start_ts < :e ORDER BY sl.slot_start_ts"""), {"f": facility_id, "s": start, "e": end})).all()
    return docks, appts, now


async def propose(db: AsyncSession, facility_id: UUID, day_start: datetime, day_end: datetime, now: datetime) -> dict[str, Any]:
    docks_by_id, appts, _ = await _load(db, facility_id, day_start, day_end, now)
    docks = list(docks_by_id.values())
    all_slots = [s for d in docks for s in d.slots]
    if not all_slots:
        return {"movable": 0, "note": "no_slots", "writes": 0, "scorecards": {}, "moves": []}
    slot_min = int(min((s.end - s.start) for s in all_slots).total_seconds() // 60)
    index = {s.id: (d, i) for d in docks for i, s in enumerate(d.slots)}
    items, fixed = [], set()
    for a in appts:
        movable = a.appointment_status in ("CONFIRMED", "PENDING_CONFIRMATION") and a.gate_in_ts is None and a.slot_start_ts > now
        d, i = index.get(a.slot_id, (docks_by_id[a.dock_id], 0))
        it = Item(a.shipment_id, a.code, a.priority_code, a.required_dock_type, a.temperature_control_required, a.load_weight_kg, a.expected_unload_min,
                  max(a.declared_eta or a.original_eta_ts, now), a.booked_at, d.code, a.slot_start_ts, a.slot_id, a.carrier_name)
        if movable:
            items.append(it)
        else:
            for s in d.slots[i:i + _needs(it, slot_min)]:
                fixed.add(s.id)
    # the slots the movable loads sit in today are released for planning (they are movable), fixed loads keep theirs
    cur_starts = {i.shipment_id: i.cur_start for i in items}
    cur_docks = {i.shipment_id: i.cur_dock for i in items}
    cards: dict[str, Any] = {"current": scorecard(items, cur_starts, cur_docks, current=True)}
    placed: dict[str, dict] = {}
    for name in ("fcfs", "proposed"):
        res = schedule(items, docks, fixed, slot_min, name)
        placed[name] = res
        cards[name] = scorecard(items, {k: v[1][0].start for k, v in res.items()}, {k: v[0].code for k, v in res.items()})
    moves = []
    for it in sorted(items, key=lambda i: i.cur_start):
        r = placed["proposed"].get(it.shipment_id)
        to_start, to_dock = (r[1][0].start, r[0].code) if r else (None, None)
        moves.append({"shipment": it.code, "carrier": it.carrier, "priority": it.priority, "eta": it.eta, "from_dock": it.cur_dock, "from_start": it.cur_start,
                      "to_dock": to_dock, "to_start": to_start, "wait_before_min": _wait(it, it.cur_start), "wait_after_min": _wait(it, to_start),
                      "changes": bool(r) and (to_start != it.cur_start or to_dock != it.cur_dock), "placed": bool(r)})
    cur, prop = cards["current"], cards["proposed"]
    better = prop["unplaced"] <= cur["unplaced"] and prop["priority_weighted_wait"] < cur["priority_weighted_wait"]
    return {"movable": len(items), "fixed_slots": len(fixed), "slot_minutes": slot_min, "writes": 0, "scorecards": cards, "moves": moves,
            "better_than_current": better,
            "saved_weighted_wait": cur["priority_weighted_wait"] - prop["priority_weighted_wait"],
            "rule": "Earliest feasible start; higher priority, then earlier ETA, breaks ties. Baseline: first come, first served by booking time."}


_ = (bindparam, timedelta)
