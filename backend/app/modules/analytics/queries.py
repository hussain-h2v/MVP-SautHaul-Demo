"""Read-model SQL for the analytics views. One module so every figure has one definition; everything is read-only and every
query takes a Scope that is applied here, in SQL. Cross-module joins are deliberate (a read model, like repository.py) and
nothing here writes. Times are bucketed in Asia/Kolkata.

Definitions
- on time: gate-in at or before slot start + ARRIVAL_GRACE_MIN
- wait: gate-in to unload start (dock-in when unloading never started); dwell: gate-in to gate-out
- no-show rate: NO_SHOW over current appointments whose slot has already started (cancelled and rejected excluded)
- utilisation: booked slot minutes over bookable slot minutes (open, or booked)
- bot resolution: threads in the period that neither escalated nor were taken over by a person"""
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import Period
from app.modules.analytics.scope import Scope

ARRIVAL_GRACE_MIN = 15
BOOKED = "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS','COMPLETED')"
LIVE_REQUEST = "('waiting','held','suggested')"
IST = "'Asia/Kolkata'"


def _bucket(col: str, unit: str) -> str:
    fmt = "YYYY-MM-DD HH24:00" if unit == "hour" else "YYYY-MM-DD"
    return f"to_char(date_trunc('{unit}', {col} AT TIME ZONE {IST}), '{fmt}')"


async def _all(db: AsyncSession, sql: str, params: dict) -> list:
    stmt = text(sql)
    if "fac" in params:
        stmt = stmt.bindparams(bindparam("fac", expanding=True))
    return list((await db.execute(stmt, params)).all())


def _f(v: Any, nd: int = 1) -> float:
    return round(float(v), nd) if v is not None else 0.0


def _pct(num: Any, den: Any) -> float:
    return round(100 * float(num) / float(den), 1) if den else 0.0


# ------------------------------------------------------------------ capacity
async def utilisation(db: AsyncSession, sc: Scope, p: Period) -> dict:
    sql, par = sc.clauses("sl.facility_id", None)
    base = f"""FROM appointment_slots sl JOIN docks d ON d.id = sl.dock_id JOIN facilities fa ON fa.id = sl.facility_id
      LEFT JOIN (SELECT DISTINCT slot_id FROM appointments WHERE appointment_status IN {BOOKED}) b ON b.slot_id = sl.id
      WHERE sl.slot_start_ts >= :f AND sl.slot_start_ts < :t {sql}"""
    m = "extract(epoch FROM (sl.slot_end_ts - sl.slot_start_ts)) / 60"
    avail = f"coalesce(sum({m}) FILTER (WHERE sl.slot_status = 'OPEN' OR b.slot_id IS NOT NULL), 0)"
    booked = f"coalesce(sum({m}) FILTER (WHERE b.slot_id IS NOT NULL), 0)"
    prm = {"f": p.start, "t": p.end, **par}
    tot = (await _all(db, f"SELECT {avail} AS a, {booked} AS b {base}", prm))[0]
    docks = await _all(db, f"SELECT fa.facility_name AS facility, d.dock_code, d.dock_type, {avail} AS a, {booked} AS b {base} GROUP BY 1, 2, 3 ORDER BY 1, 2", prm)
    heat = await _all(db, f"SELECT extract(isodow FROM sl.slot_start_ts AT TIME ZONE {IST})::int AS dow, extract(hour FROM sl.slot_start_ts AT TIME ZONE {IST})::int AS hr, {avail} AS a, {booked} AS b {base} GROUP BY 1, 2 ORDER BY 1, 2", prm)
    facs = await _all(db, f"SELECT fa.facility_name AS facility, {avail} AS a, {booked} AS b {base} GROUP BY 1 ORDER BY 1", prm)
    return {
        "available_min": _f(tot.a, 0), "booked_min": _f(tot.b, 0), "utilisation_pct": _pct(tot.b, tot.a),
        "by_dock": [{"facility": r.facility, "dock": r.dock_code, "type": r.dock_type, "available_min": _f(r.a, 0), "booked_min": _f(r.b, 0), "utilisation_pct": _pct(r.b, r.a)} for r in docks],
        "heatmap": [{"dow": r.dow, "hour": r.hr, "available_min": _f(r.a, 0), "booked_min": _f(r.b, 0), "utilisation_pct": _pct(r.b, r.a)} for r in heat if float(r.a) > 0],
        "by_facility": [{"facility": r.facility, "available_min": _f(r.a, 0), "booked_min": _f(r.b, 0), "utilisation_pct": _pct(r.b, r.a)} for r in facs],
    }


async def dock_events(db: AsyncSession, sc: Scope, p: Period, now: datetime) -> dict:
    sql, par = sc.clauses("d.facility_id", None)
    rows = await _all(db, f"""SELECT fa.facility_name AS facility, d.dock_code, de.event_type, count(*) AS n,
        coalesce(sum(extract(epoch FROM (least(coalesce(de.event_end_ts, CAST(:now AS timestamptz)), CAST(:t AS timestamptz)) - greatest(de.event_start_ts, CAST(:f AS timestamptz)))) / 3600), 0) AS hours
      FROM dock_status_events de JOIN docks d ON d.id = de.dock_id JOIN facilities fa ON fa.id = d.facility_id
      WHERE de.event_type <> 'REOPENED' AND de.event_start_ts < :t AND coalesce(de.event_end_ts, CAST(:now AS timestamptz)) > :f {sql}
      GROUP BY 1, 2, 3 ORDER BY hours DESC""", {"f": p.start, "t": p.end, "now": now, **par})
    return {"events": sum(r.n for r in rows), "lost_hours": round(sum(float(r.hours) for r in rows), 1),
            "rows": [{"facility": r.facility, "dock": r.dock_code, "type": r.event_type, "events": r.n, "hours": _f(r.hours)} for r in rows]}


# ------------------------------------------------------------------ arrivals
def _arrival_base(sc: Scope, extra: str = "") -> tuple[str, dict]:
    sql, par = sc.clauses("sl.facility_id", "sh.carrier_id")
    return (f"""FROM facility_checkins ck JOIN shipments sh ON sh.id = ck.shipment_id
      JOIN appointments a ON a.shipment_id = sh.id AND a.is_current AND a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS','COMPLETED','NO_SHOW')
      JOIN appointment_slots sl ON sl.id = a.slot_id
      WHERE ck.gate_in_ts >= :f AND ck.gate_in_ts < :t {sql} {extra}"""), par


_ON_TIME = f"(ck.gate_in_ts <= sl.slot_start_ts + interval '{ARRIVAL_GRACE_MIN} minutes')"
_WAIT = "extract(epoch FROM (coalesce(ck.unload_start_ts, ck.dock_in_ts) - ck.gate_in_ts)) / 60"
_DWELL = "extract(epoch FROM (ck.gate_out_ts - ck.gate_in_ts)) / 60"
_LATE_MIN = "greatest(0, extract(epoch FROM (ck.gate_in_ts - sl.slot_start_ts)) / 60)"


async def arrivals(db: AsyncSession, sc: Scope, p: Period) -> dict:
    base, par = _arrival_base(sc)
    r = (await _all(db, f"""SELECT count(*) AS n, count(*) FILTER (WHERE {_ON_TIME}) AS on_time,
        avg({_WAIT}) FILTER (WHERE coalesce(ck.unload_start_ts, ck.dock_in_ts) IS NOT NULL) AS wait,
        avg({_DWELL}) FILTER (WHERE ck.gate_out_ts IS NOT NULL) AS dwell,
        percentile_cont(0.9) WITHIN GROUP (ORDER BY {_WAIT}) FILTER (WHERE coalesce(ck.unload_start_ts, ck.dock_in_ts) IS NOT NULL) AS wait_p90 {base}""",
                     {"f": p.start, "t": p.end, **par}))[0]
    return {"arrivals": r.n, "on_time": r.on_time, "late": r.n - r.on_time, "on_time_rate": _pct(r.on_time, r.n) if r.n else 0.0,
            "avg_wait_min": _f(r.wait), "avg_dwell_min": _f(r.dwell), "wait_p90_min": _f(r.wait_p90)}


async def no_shows(db: AsyncSession, sc: Scope, p: Period, now: datetime) -> dict:
    sql, par = sc.clauses("sl.facility_id", "sh.carrier_id")
    r = (await _all(db, f"""SELECT count(*) AS n, count(*) FILTER (WHERE a.appointment_status = 'NO_SHOW') AS ns,
        count(*) FILTER (WHERE a.appointment_status = 'COMPLETED') AS done
      FROM appointments a JOIN appointment_slots sl ON sl.id = a.slot_id JOIN shipments sh ON sh.id = a.shipment_id
      WHERE a.is_current AND a.appointment_status NOT IN ('CANCELLED','REJECTED') AND sl.slot_start_ts >= :f AND sl.slot_start_ts < LEAST(CAST(:t AS timestamptz), CAST(:now AS timestamptz)) {sql}""",
                     {"f": p.start, "t": p.end, "now": now, **par}))[0]
    return {"scheduled": r.n, "no_shows": r.ns, "no_show_rate": _pct(r.ns, r.n), "completed": r.done}


# ------------------------------------------------------------------ desk and bot
async def requests(db: AsyncSession, sc: Scope, p: Period) -> dict:
    sql, par = sc.clauses("sh.destination_facility_id", "sh.carrier_id")
    base = f"FROM approval_requests ar JOIN shipments sh ON sh.id = ar.shipment_id WHERE ar.created_at >= :f AND ar.created_at < :t {sql}"
    prm = {"f": p.start, "t": p.end, **par}
    r = (await _all(db, f"""SELECT count(*) AS n,
        avg(extract(epoch FROM (ar.decided_at - ar.created_at)) / 60) FILTER (WHERE ar.decided_at IS NOT NULL) AS dec,
        percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM (ar.decided_at - ar.created_at)) / 60) FILTER (WHERE ar.decided_at IS NOT NULL) AS dec90 {base}""", prm))[0]
    mix = await _all(db, f"SELECT ar.status, count(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC", prm)
    live = (await _all(db, f"SELECT count(*) AS n FROM approval_requests ar JOIN shipments sh ON sh.id = ar.shipment_id WHERE ar.status IN {LIVE_REQUEST} {sql}", par))[0]
    holds = (await _all(db, f"SELECT count(*) AS n FROM slot_holds h JOIN shipments sh ON sh.id = h.shipment_id WHERE h.status = 'expired' AND h.updated_at >= :f AND h.updated_at < :t {sql}", prm))[0]
    return {"requests": r.n, "avg_decision_min": _f(r.dec), "decision_p90_min": _f(r.dec90), "backlog": live.n, "holds_expired": holds.n,
            "mix": [{"key": m.status, "count": m.n, "share": _pct(m.n, r.n)} for m in mix]}


async def escalations(db: AsyncSession, sc: Scope, p: Period) -> dict:
    sql, par = sc.clauses("sh.destination_facility_id", "sh.carrier_id")
    base = f"FROM escalations e LEFT JOIN shipments sh ON sh.id = e.shipment_id WHERE e.created_at >= :f AND e.created_at < :t {sql}"
    prm = {"f": p.start, "t": p.end, **par}
    rows = await _all(db, f"SELECT e.reason_code, count(*) AS n, avg(extract(epoch FROM (e.closed_at - e.created_at)) / 60) FILTER (WHERE e.closed_at IS NOT NULL) AS res {base} GROUP BY 1 ORDER BY 2 DESC", prm)
    total = sum(r.n for r in rows)
    resolved = (await _all(db, f"SELECT count(*) FILTER (WHERE e.status = 'resolved') AS n, avg(extract(epoch FROM (e.closed_at - e.created_at)) / 60) FILTER (WHERE e.closed_at IS NOT NULL) AS res {base}", prm))[0]
    return {"escalations": total, "resolved": resolved.n, "avg_resolution_min": _f(resolved.res),
            "by_reason": [{"key": r.reason_code, "count": r.n, "share": _pct(r.n, total), "avg_resolution_min": _f(r.res)} for r in rows]}


async def delays(db: AsyncSession, sc: Scope, p: Period) -> dict:
    sql, par = sc.clauses("sh.destination_facility_id", "sh.carrier_id")
    base = f"FROM eta_updates eu JOIN shipments sh ON sh.id = eu.shipment_id WHERE eu.source_type = 'DRIVER_DECLARED' AND eu.created_at >= :f AND eu.created_at < :t {sql}"
    prm = {"f": p.start, "t": p.end, **par}
    late = "extract(epoch FROM (eu.declared_eta_ts - sh.original_eta_ts)) / 60"
    tot = (await _all(db, f"SELECT count(*) AS n, count(DISTINCT eu.shipment_id) AS ships, avg({late}) FILTER (WHERE {late} > 0) AS avg {base}", prm))[0]
    rows = await _all(db, f"SELECT coalesce(eu.delay_reason_code, 'UNSPECIFIED') AS k, count(*) AS n, avg({late}) FILTER (WHERE {late} > 0) AS avg {base} GROUP BY 1 ORDER BY 2 DESC", prm)
    return {"delay_reports": tot.n, "delayed_shipments": tot.ships, "avg_declared_delay_min": _f(tot.avg),
            "causes": [{"key": r.k, "count": r.n, "share": _pct(r.n, tot.n), "avg_delay_min": _f(r.avg)} for r in rows]}


async def bot(db: AsyncSession, sc: Scope, p: Period) -> dict:
    sql, par = sc.clauses("sh.destination_facility_id", "sh.carrier_id")
    scoped = sc.facility_ids is not None or sc.carrier_id is not None
    base = f"""FROM chat_threads ct {'JOIN' if scoped else 'LEFT JOIN'} shipments sh ON sh.id = ct.shipment_id
      WHERE ct.opened_at >= :f AND ct.opened_at < :t {sql}"""
    human = """(ct.thread_status = 'ESCALATED' OR ct.taken_over_by_user_id IS NOT NULL OR EXISTS (
        SELECT 1 FROM escalations e JOIN driver_exceptions de ON de.id = e.exception_id WHERE de.thread_id = ct.id))"""
    r = (await _all(db, f"SELECT count(*) AS n, count(*) FILTER (WHERE {human}) AS human {base}", {"f": p.start, "t": p.end, **par}))[0]
    return {"threads": r.n, "needed_a_person": r.human, "bot_resolved": r.n - r.human, "bot_resolution_rate": _pct(r.n - r.human, r.n) if r.n else 0.0}


async def throughput(db: AsyncSession, sc: Scope, p: Period, now: datetime) -> dict:
    base, par = _arrival_base(sc, "")
    r = (await _all(db, f"SELECT count(*) FILTER (WHERE ck.gate_out_ts IS NOT NULL) AS out, count(*) FILTER (WHERE a.appointment_status = 'COMPLETED') AS done {base}", {"f": p.start, "t": p.end, **par}))[0]
    return {"loads_completed": r.done, "loads_out": r.out}


# ------------------------------------------------------------------ carrier
async def carrier_tables(db: AsyncSession, sc: Scope, p: Period, now: datetime) -> dict:
    base, par = _arrival_base(sc)
    prm = {"f": p.start, "t": p.end, **par}
    drv = await _all(db, f"""SELECT dr.code, dr.driver_name, count(*) AS trips, count(*) FILTER (WHERE NOT {_ON_TIME}) AS late,
        avg({_LATE_MIN}) FILTER (WHERE NOT {_ON_TIME}) AS late_min {base.replace('JOIN appointment_slots sl', 'JOIN drivers dr ON dr.id = sh.driver_id JOIN appointment_slots sl')} GROUP BY 1, 2 ORDER BY late DESC, trips DESC""", prm)
    lanes = await _all(db, f"""SELECT sh.origin_city AS origin, fa.facility_name AS facility, count(*) AS trips, count(*) FILTER (WHERE NOT {_ON_TIME}) AS late,
        avg({_LATE_MIN}) FILTER (WHERE NOT {_ON_TIME}) AS late_min, avg({_WAIT}) FILTER (WHERE coalesce(ck.unload_start_ts, ck.dock_in_ts) IS NOT NULL) AS wait
      {base.replace('JOIN appointment_slots sl', 'JOIN facilities fa ON fa.id = sh.destination_facility_id JOIN appointment_slots sl')} GROUP BY 1, 2 ORDER BY late DESC, trips DESC""", prm)
    sql, par2 = sc.clauses("sh.destination_facility_id", "sh.carrier_id")
    delays_by_driver = await _all(db, f"""SELECT dr.code, count(*) AS n FROM eta_updates eu JOIN shipments sh ON sh.id = eu.shipment_id JOIN drivers dr ON dr.id = sh.driver_id
      WHERE eu.source_type = 'DRIVER_DECLARED' AND eu.created_at >= :f AND eu.created_at < :t {sql} GROUP BY 1""", {"f": p.start, "t": p.end, **par2})
    reports = {r.code: r.n for r in delays_by_driver}
    ch = (await _all(db, f"""SELECT count(*) FILTER (WHERE a.replaced_appointment_id IS NOT NULL AND a.booked_at >= :f AND a.booked_at < :t) AS moved,
        count(*) FILTER (WHERE a.appointment_status = 'CANCELLED' AND a.cancelled_at >= :f AND a.cancelled_at < :t) AS cancelled
      FROM appointments a JOIN appointment_slots sl ON sl.id = a.slot_id JOIN shipments sh ON sh.id = a.shipment_id WHERE true {sql.replace('sh.destination_facility_id', 'sl.facility_id')}""", {"f": p.start, "t": p.end, **par2}))[0]
    off = (await _all(db, f"""SELECT count(*) FILTER (WHERE sh.offer_status = 'declined') AS declined, count(*) FILTER (WHERE sh.offer_status = 'accepted') AS accepted,
        count(*) FILTER (WHERE sh.offer_status IN ('offered','accepted','declined')) AS offered
      FROM shipments sh WHERE sh.updated_at >= :f AND sh.updated_at < :t {sql}""", {"f": p.start, "t": p.end, **par2}))[0]
    return {
        "by_driver": [{"code": r.code, "driver": r.driver_name, "trips": r.trips, "late": r.late, "late_rate": _pct(r.late, r.trips), "avg_late_min": _f(r.late_min),
                       "delay_reports": reports.get(r.code, 0)} for r in drv],
        "by_lane": [{"origin": r.origin, "facility": r.facility, "trips": r.trips, "late": r.late, "late_rate": _pct(r.late, r.trips), "avg_late_min": _f(r.late_min), "avg_wait_min": _f(r.wait)} for r in lanes],
        "slot_moves": ch.moved, "slot_cancellations": ch.cancelled, "offers": off.offered, "offers_declined": off.declined,
        "decline_rate": _pct(off.declined, off.offered),
    }


# ------------------------------------------------------------------ time series
async def series(db: AsyncSession, sc: Scope, p: Period, now: datetime) -> list[dict]:
    unit = p.bucket
    out: dict[str, dict] = {k: {"bucket": k, "arrivals": 0, "late": 0, "loads": 0, "requests": 0, "escalations": 0, "delay_reports": 0, "no_shows": 0,
                                "available_min": 0.0, "booked_min": 0.0, "utilisation_pct": 0.0, "avg_wait_min": 0.0} for k in p.labels()}
    prm = {"f": p.start, "t": p.end}

    def put(label: str, **kw: Any) -> None:
        if label in out:
            out[label].update(kw)

    sql, par = sc.clauses("sl.facility_id", None)
    m = "extract(epoch FROM (sl.slot_end_ts - sl.slot_start_ts)) / 60"
    for r in await _all(db, f"""SELECT {_bucket('sl.slot_start_ts', unit)} AS k,
        coalesce(sum({m}) FILTER (WHERE sl.slot_status = 'OPEN' OR b.slot_id IS NOT NULL), 0) AS a, coalesce(sum({m}) FILTER (WHERE b.slot_id IS NOT NULL), 0) AS b
      FROM appointment_slots sl LEFT JOIN (SELECT DISTINCT slot_id FROM appointments WHERE appointment_status IN {BOOKED}) b ON b.slot_id = sl.id
      WHERE sl.slot_start_ts >= :f AND sl.slot_start_ts < :t {sql} GROUP BY 1""", {**prm, **par}):
        put(r.k, available_min=_f(r.a, 0), booked_min=_f(r.b, 0), utilisation_pct=_pct(r.b, r.a))
    base, par = _arrival_base(sc)
    for r in await _all(db, f"""SELECT {_bucket('ck.gate_in_ts', unit)} AS k, count(*) AS n, count(*) FILTER (WHERE NOT {_ON_TIME}) AS late,
        avg({_WAIT}) FILTER (WHERE coalesce(ck.unload_start_ts, ck.dock_in_ts) IS NOT NULL) AS wait, count(*) FILTER (WHERE a.appointment_status = 'COMPLETED') AS done {base} GROUP BY 1""", {**prm, **par}):
        put(r.k, arrivals=r.n, late=r.late, avg_wait_min=_f(r.wait), loads=r.done)
    sql, par = sc.clauses("sh.destination_facility_id", "sh.carrier_id")
    for r in await _all(db, f"SELECT {_bucket('ar.created_at', unit)} AS k, count(*) AS n FROM approval_requests ar JOIN shipments sh ON sh.id = ar.shipment_id WHERE ar.created_at >= :f AND ar.created_at < :t {sql} GROUP BY 1", {**prm, **par}):
        put(r.k, requests=r.n)
    for r in await _all(db, f"SELECT {_bucket('e.created_at', unit)} AS k, count(*) AS n FROM escalations e LEFT JOIN shipments sh ON sh.id = e.shipment_id WHERE e.created_at >= :f AND e.created_at < :t {sql} GROUP BY 1", {**prm, **par}):
        put(r.k, escalations=r.n)
    for r in await _all(db, f"SELECT {_bucket('eu.created_at', unit)} AS k, count(*) AS n FROM eta_updates eu JOIN shipments sh ON sh.id = eu.shipment_id WHERE eu.source_type = 'DRIVER_DECLARED' AND eu.created_at >= :f AND eu.created_at < :t {sql} GROUP BY 1", {**prm, **par}):
        put(r.k, delay_reports=r.n)
    sql, par = sc.clauses("sl.facility_id", "sh.carrier_id")
    for r in await _all(db, f"""SELECT {_bucket('sl.slot_start_ts', unit)} AS k, count(*) AS n FROM appointments a JOIN appointment_slots sl ON sl.id = a.slot_id JOIN shipments sh ON sh.id = a.shipment_id
      WHERE a.is_current AND a.appointment_status = 'NO_SHOW' AND sl.slot_start_ts >= :f AND sl.slot_start_ts < :t {sql} GROUP BY 1""", {**prm, **par}):
        put(r.k, no_shows=r.n)
    _ = now
    return list(out.values())
