from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.modules.analytics import repository
from app.modules.auth.deps import Principal
from app.modules.booking import service as booking_service
from app.modules.exceptions import service as exceptions_service

KINDS = {
    "utilisation": ["date", "dock_code", "available_min", "booked_min", "utilisation_pct"],
    "detention": ["date", "shipment_code", "carrier_name", "gate_in_ts", "unload_start_ts", "detention_min"],
    "overrun": ["date", "shipment_code", "carrier_name", "expected_min", "actual_min", "overrun_min"],
    "noshow": ["date", "no_shows", "scheduled", "no_show_rate_pct"],
}
MAX_RANGE_DAYS = 93


def _minutes(slot) -> int:
    return int((slot.slot_end_ts - slot.slot_start_ts).total_seconds() // 60)


async def _utilisation_rows(db: AsyncSession, facility_id: UUID, tz: str, start, end) -> list[dict[str, Any]]:
    zone = ZoneInfo(tz)
    agg: dict[tuple[date, str], list[int]] = defaultdict(lambda: [0, 0])
    for slot, dock_code, booked in await repository.slots_with_booking(db, facility_id, start, end):
        if slot.slot_status != "OPEN" and not booked:
            continue  # blocked/closed and unused capacity is not available capacity
        key = (slot.slot_start_ts.astimezone(zone).date(), dock_code)
        agg[key][0] += _minutes(slot)
        if booked:
            agg[key][1] += _minutes(slot)
    return [{"date": d.isoformat(), "dock_code": code, "available_min": a, "booked_min": b,
             "utilisation_pct": round(100 * b / a, 1) if a else 0.0} for (d, code), (a, b) in sorted(agg.items())]


async def facility_report(db: AsyncSession, p: Principal, facility_id: UUID, date_from: date, date_to: date,
                          kind: str) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValidationAppError(f"kind must be one of {', '.join(KINDS)}")
    if date_to < date_from or (date_to - date_from).days > MAX_RANGE_DAYS:
        raise ValidationAppError(f"date range must be 0-{MAX_RANGE_DAYS} days")
    fac = await booking_service.resolve_facility(db, p, facility_id)
    zone = ZoneInfo(fac.timezone)
    start, _ = booking_service.day_bounds(date_from, fac.timezone)
    _, end = booking_service.day_bounds(date_to, fac.timezone)
    if kind == "utilisation":
        rows = await _utilisation_rows(db, fac.id, fac.timezone, start, end)
    elif kind == "noshow":
        per: dict[date, list[int]] = defaultdict(lambda: [0, 0])
        for status, slot_start in await repository.appointments_in_window(db, fac.id, start, end):
            d = slot_start.astimezone(zone).date()
            per[d][1] += 1
            per[d][0] += status == "NO_SHOW"
        rows = [{"date": d.isoformat(), "no_shows": n, "scheduled": t,
                 "no_show_rate_pct": round(100 * n / t, 1) if t else 0.0} for d, (n, t) in sorted(per.items())]
    else:
        from app.modules.carriers import service as carriers_service

        pairs = await repository.checkins_in_window(db, fac.id, start, end)
        carriers = await carriers_service.names(db, list({s.carrier_id for _, s in pairs if s.carrier_id}))
        rows = []
        for ck, s in pairs:
            if not ck.unload_start_ts:
                continue
            day = ck.gate_in_ts.astimezone(zone).date().isoformat()
            if kind == "detention":
                rows.append({"date": day, "shipment_code": s.code, "carrier_name": carriers.get(s.carrier_id),
                             "gate_in_ts": ck.gate_in_ts, "unload_start_ts": ck.unload_start_ts,
                             "detention_min": max(0, int((ck.unload_start_ts - ck.gate_in_ts).total_seconds() // 60))})
            elif ck.unload_end_ts:
                actual = int((ck.unload_end_ts - ck.unload_start_ts).total_seconds() // 60)
                rows.append({"date": day, "shipment_code": s.code, "carrier_name": carriers.get(s.carrier_id),
                             "expected_min": s.expected_unload_min, "actual_min": actual,
                             "overrun_min": actual - s.expected_unload_min})
    return {"kind": kind, "columns": KINDS[kind], "rows": rows}


async def facility_home(db: AsyncSession, p: Principal, facility_id: UUID) -> dict[str, Any]:
    fac = await booking_service.resolve_facility(db, p, facility_id)
    today = booking_service.local_today(fac.timezone)
    start, end = booking_service.day_bounds(today, fac.timezone)
    util = await _utilisation_rows(db, fac.id, fac.timezone, start, end)
    available, booked = sum(r["available_min"] for r in util), sum(r["booked_min"] for r in util)
    return {
        "date": today.isoformat(),
        "utilisation_pct": round(100 * booked / available, 1) if available else 0.0,
        "inbound_count": len(await booking_service.inbound(db, p, fac.id, today)),
        "in_yard_count": await booking_service.yard_counts(db, fac.id),
        "active_holds": 0,
        "open_exceptions": await exceptions_service.count_open_for_facility(db, fac.id),
        "dock_status": await repository.dock_status_counts(db, fac.id, booking_service.now()),
        "pending_confirmations": await booking_service.pending_count(db, p, fac.id),
    }



