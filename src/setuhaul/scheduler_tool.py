"""Optional extension: a facility-level scheduling tool.

The agent in conversation.py only ever looks at one driver's shipment. This
tool looks at a whole facility and every truck in or heading to it at once,
and proposes a sequence per dock. It is a controlled tool: it reads only
structured state (shipments, ETAs, check-ins, appointments, dock status)
and returns a ranked schedule. It never reads chat text.

Business concept -> scheduling model (per the brief's own table):
  shipment            -> job
  dock                -> machine (limited resource)
  effective ETA        -> release time (job cannot start before this)
  gate-in              -> evidence the job is actually ready now
  expected_unload_min  -> processing time
  existing appointment -> a due-time preference, not a hard constraint
  truck already in dock -> a fixed task the schedule cannot move
  priority_code         -> a weight on how costly waiting/lateness is

Design choice (per the brief's advice to start simple and justify moving
further): this uses a single transparent dispatch rule -- at each point a
dock frees up, among the jobs that have "released" (ETA has passed) and are
not yet finished, pick the one with the highest priority weight, breaking
ties by whichever released earliest. This is a priority-weighted greedy
list-scheduling rule, the textbook starting point for job-shop-like
problems, and it is explainable in one sentence to a non-technical
operations lead. Constraint programming (CP-SAT) is not used here because
the fleet-and-dock scale in this snapshot (a handful of trucks, one
facility) does not need it, and the brief asks for CP only "if you can
explain why" -- here, a greedy priority rule already gives a defensible,
auditable answer.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .clock import SimClock
from .tools import PRIORITY_WEIGHT, _dock_compatible


@dataclass
class Job:
    shipment_id: str
    priority_code: str
    release_ts: datetime
    duration_min: int
    required_dock_type: str
    temp_required: bool
    load_weight_kg: int
    fixed_dock_code: Optional[str] = None       # already in a dock / unload in progress
    fixed_finish_ts: Optional[datetime] = None
    appointment_start_ts: Optional[datetime] = None


@dataclass
class DockMachine:
    dock_code: str
    dock_type: str
    supports_refrigerated: int
    max_vehicle_weight_kg: int
    free_at: datetime


@dataclass
class ScheduledEntry:
    shipment_id: str
    dock_code: str
    start_ts: datetime
    end_ts: datetime
    waited_min: float
    missed_own_appointment: bool


def _load_jobs(
    conn: sqlite3.Connection,
    facility_id: str,
    as_of: datetime,
    shipment_ids: Optional[list[str]] = None,
) -> list[Job]:
    shipment_filter = ""
    params: tuple = (facility_id,)
    if shipment_ids is not None:
        if not shipment_ids:
            return []
        shipment_filter = f" AND s.shipment_id IN ({','.join('?' for _ in shipment_ids)})"
        params = (facility_id, *shipment_ids)

    rows = conn.execute(
        f"""
        SELECT s.shipment_id, s.priority_code, s.required_dock_type,
               s.temperature_control_required, s.load_weight_kg, s.expected_unload_min,
               s.current_status, le.effective_eta_ts,
               fc.queue_state, fc.gate_in_ts, fc.unload_start_ts, fc.actual_dock_id,
               d.dock_code AS fixed_dock_code,
               ap.appointment_id, sl.slot_start_ts
        FROM shipments s
        JOIN v_latest_eta le ON le.shipment_id = s.shipment_id
        LEFT JOIN facility_checkins fc ON fc.shipment_id = s.shipment_id
        LEFT JOIN docks d ON d.dock_id = fc.actual_dock_id
        LEFT JOIN appointments ap ON ap.shipment_id = s.shipment_id AND ap.is_current = 1
            AND ap.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
        LEFT JOIN appointment_slots sl ON sl.slot_id = ap.slot_id
        WHERE s.destination_facility_id = ?
          AND s.current_status IN ('ASSIGNED','IN_TRANSIT','AT_GATE','WAITING','IN_DOCK')
          {shipment_filter}
        """,
        params,
    ).fetchall()

    jobs = []
    for r in rows:
        release = SimClock.parse(r["effective_eta_ts"])
        if r["gate_in_ts"]:
            gate = SimClock.parse(r["gate_in_ts"])
            release = min(release, gate)
        fixed_finish = None
        if r["current_status"] == "IN_DOCK" and r["unload_start_ts"]:
            fixed_finish = SimClock.parse(r["unload_start_ts"]) + timedelta(minutes=r["expected_unload_min"])
        jobs.append(Job(
            shipment_id=r["shipment_id"], priority_code=r["priority_code"], release_ts=release,
            duration_min=r["expected_unload_min"], required_dock_type=r["required_dock_type"],
            temp_required=bool(r["temperature_control_required"]), load_weight_kg=r["load_weight_kg"],
            fixed_dock_code=r["fixed_dock_code"] if r["current_status"] == "IN_DOCK" else None,
            fixed_finish_ts=fixed_finish,
            appointment_start_ts=SimClock.parse(r["slot_start_ts"]) if r["slot_start_ts"] else None,
        ))
    return jobs


def _load_docks(conn: sqlite3.Connection, facility_id: str, as_of: datetime) -> list[DockMachine]:
    rows = conn.execute(
        "SELECT dock_code, dock_type, supports_refrigerated, max_vehicle_weight_kg "
        "FROM docks WHERE facility_id = ? AND dock_status = 'ACTIVE'",
        (facility_id,),
    ).fetchall()
    return [DockMachine(r["dock_code"], r["dock_type"], r["supports_refrigerated"],
                         r["max_vehicle_weight_kg"], as_of) for r in rows]


def _priority_rule(jobs: list[Job], docks: list[DockMachine], as_of: datetime) -> list[ScheduledEntry]:
    machines = {d.dock_code: d for d in docks}
    for j in jobs:
        if j.fixed_dock_code and j.fixed_dock_code in machines:
            finish = j.fixed_finish_ts or as_of
            machines[j.fixed_dock_code].free_at = max(machines[j.fixed_dock_code].free_at, finish)

    remaining = [j for j in jobs if not j.fixed_dock_code]
    schedule: list[ScheduledEntry] = []

    while remaining:
        best = None
        for j in remaining:
            eligible = [m for m in machines.values()
                        if _dock_compatible(j.required_dock_type, j.temp_required, j.load_weight_kg,
                                             m.dock_type, m.supports_refrigerated, m.max_vehicle_weight_kg)]
            if not eligible:
                continue
            m = min(eligible, key=lambda d: d.free_at)
            start = max(m.free_at, j.release_ts)
            key = (
                start,
                -PRIORITY_WEIGHT.get(j.priority_code, 0),
                j.release_ts,
                j.shipment_id,
            )
            if best is None or key < best[0]:
                best = (key, j, m, start)
        if best is None:
            break
        _, job, machine, start = best
        end = start + timedelta(minutes=job.duration_min)
        machine.free_at = end
        waited = max(0.0, (start - job.release_ts).total_seconds() / 60.0)
        missed = bool(job.appointment_start_ts and start > job.appointment_start_ts + timedelta(minutes=15))
        schedule.append(ScheduledEntry(job.shipment_id, machine.dock_code, start, end, waited, missed))
        remaining.remove(job)

    return schedule


def _fcfs_rule(jobs: list[Job], docks: list[DockMachine], as_of: datetime) -> list[ScheduledEntry]:
    machines = {d.dock_code: d for d in docks}
    for j in jobs:
        if j.fixed_dock_code and j.fixed_dock_code in machines:
            finish = j.fixed_finish_ts or as_of
            machines[j.fixed_dock_code].free_at = max(machines[j.fixed_dock_code].free_at, finish)

    ordered = sorted([j for j in jobs if not j.fixed_dock_code], key=lambda j: j.release_ts)
    schedule: list[ScheduledEntry] = []
    for job in ordered:
        eligible = [m for m in machines.values()
                    if _dock_compatible(job.required_dock_type, job.temp_required, job.load_weight_kg,
                                         m.dock_type, m.supports_refrigerated, m.max_vehicle_weight_kg)]
        if not eligible:
            continue
        m = min(eligible, key=lambda d: d.free_at)
        start = max(m.free_at, job.release_ts)
        end = start + timedelta(minutes=job.duration_min)
        m.free_at = end
        waited = max(0.0, (start - job.release_ts).total_seconds() / 60.0)
        missed = bool(job.appointment_start_ts and start > job.appointment_start_ts + timedelta(minutes=15))
        schedule.append(ScheduledEntry(job.shipment_id, m.dock_code, start, end, waited, missed))
    return schedule


def propose_schedule(
    conn: sqlite3.Connection,
    clock: SimClock,
    facility_id: str,
    *,
    shipment_ids: Optional[list[str]] = None,
) -> dict:
    as_of = clock.now()
    jobs = _load_jobs(conn, facility_id, as_of, shipment_ids)
    priority_sched = _priority_rule(jobs, _load_docks(conn, facility_id, as_of), as_of)
    fcfs_sched = _fcfs_rule(jobs, _load_docks(conn, facility_id, as_of), as_of)

    def summarize(sched: list[ScheduledEntry]) -> dict:
        if not sched:
            return {
                "avg_wait_min": 0.0,
                "total_wait_min": 0.0,
                "priority_weighted_wait_min": 0.0,
                "missed_appointments": 0,
                "entries": [],
            }
        return {
            "avg_wait_min": round(sum(e.waited_min for e in sched) / len(sched), 1),
            "total_wait_min": round(sum(e.waited_min for e in sched), 1),
            "priority_weighted_wait_min": round(
                sum(
                    e.waited_min
                    * PRIORITY_WEIGHT.get(
                        next(j.priority_code for j in jobs if j.shipment_id == e.shipment_id),
                        0,
                    )
                    for e in sched
                ),
                1,
            ),
            "missed_appointments": sum(1 for e in sched if e.missed_own_appointment),
            "entries": [
                {"shipment_id": e.shipment_id, "dock": e.dock_code,
                 "start": SimClock.format(e.start_ts), "end": SimClock.format(e.end_ts),
                 "waited_min": round(e.waited_min, 1), "missed_own_appointment": e.missed_own_appointment}
                for e in sched
            ],
        }

    fixed_jobs = [
        {
            "shipment_id": job.shipment_id,
            "dock": job.fixed_dock_code,
            "estimated_finish": SimClock.format(job.fixed_finish_ts) if job.fixed_finish_ts else None,
            "rescheduled": False,
        }
        for job in jobs
        if job.fixed_dock_code is not None
    ]
    return {
        "objective": (
            "Assign the earliest feasible dock start first; for equal starts, prefer higher priority, "
            "then earlier ETA and shipment ID. Compare proposals by priority-weighted waiting minutes "
            "(wait minutes × priority weight), total waiting minutes, and missed appointments."
        ),
        "facility_id": facility_id,
        "shipment_ids": [job.shipment_id for job in jobs],
        "fixed_in_progress": fixed_jobs,
        "priority_rule": summarize(priority_sched),
        "naive_fcfs": summarize(fcfs_sched),
    }
