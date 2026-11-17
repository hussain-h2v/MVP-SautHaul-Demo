from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointments import service as appointments_service
from app.modules.appointments.models import ACTIVE_STATUSES
from app.modules.carriers import service as carriers_service
from app.modules.coordinator import desk_board_repository as repo
from app.modules.coordinator.desk_board_schemas import BoardOut, BoardRow, Stages
from app.modules.drivers import service as drivers_service
from app.modules.eta import service as eta_service

PRIORITY = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
STALE_ETA_MIN = 15


def _bounds(d: date, tz: str) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=ZoneInfo(tz))
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


async def board(db: AsyncSession, facility_id: UUID | None, day: date | None, now: datetime | None = None) -> BoardOut:
    now = now or datetime.now(UTC)
    cands = await repo.candidates(db, facility_id)
    ids = [s.id for s, _, _ in cands]
    etas = await eta_service.latest_eta_for(db, ids)
    appts = await appointments_service.current_for_shipments(db, ids)
    checkins = await appointments_service.checkins_for_shipments(db, ids)
    slots = await repo.slot_info(db, [a.slot_id for a in appts.values() if a.appointment_status in ACTIVE_STATUSES])
    carriers = await carriers_service.names(db, list({s.carrier_id for s, _, _ in cands if s.carrier_id}))
    drivers = await drivers_service.names(db, list({s.driver_id for s, _, _ in cands if s.driver_id}))
    stages: dict[str, list[tuple]] = {k: [] for k in ("travelling", "late", "in_yard", "unloading", "done")}
    for s, fcode, tz in cands:
        local_day = day or now.astimezone(ZoneInfo(tz)).date()
        lo, hi = _bounds(local_day, tz)
        eta = etas.get(s.id) or {}
        eta_ts = eta.get("eta_ts")
        a = appts.get(s.id)
        a = a if a is not None and a.appointment_status in ACTIVE_STATUSES else None
        slot = slots.get(a.slot_id) if a else None
        slot_start = slot[2] if slot else None
        ck = checkins.get(s.id)
        in_window = (eta_ts is not None and lo <= eta_ts < hi) or (slot_start is not None and lo <= slot_start < hi)
        late_min = None
        if s.current_status == "COMPLETED":
            if not (ck and ck.unload_end_ts and lo <= ck.unload_end_ts < hi):
                continue
            stage = "done"
        elif not in_window:
            continue
        elif s.current_status == "IN_DOCK":
            stage = "unloading"
        elif s.current_status in ("AT_GATE", "WAITING"):
            stage = "in_yard"
        elif ck is not None:
            continue  # arrived: tracked through the yard stages
        else:
            stage = "travelling"
            if eta_ts and slot_start and eta_ts > slot_start:
                stage, late_min = "late", int((eta_ts - slot_start).total_seconds() // 60)
            elif eta_ts and now > eta_ts + timedelta(minutes=STALE_ETA_MIN):
                stage, late_min = "late", int((now - eta_ts).total_seconds() // 60)
        row = BoardRow(shipment_id=s.id, code=s.code, carrier_name=carriers.get(s.carrier_id),
                       driver_name=drivers.get(s.driver_id), facility_code=fcode, priority_code=s.priority_code,
                       current_status=s.current_status, eta_ts=eta_ts, eta_confidence=eta.get("eta_confidence"),
                       slot_code=slot[0] if slot else None, dock_code=slot[1] if slot else None,
                       slot_start_ts=slot_start, late_min=late_min)
        stages[stage].append((PRIORITY.get(s.priority_code, 2), eta_ts or slot_start or now, row))
    out = {k: [r for _, _, r in sorted(v, key=lambda t: (t[0], t[1]))] for k, v in stages.items()}
    return BoardOut(date=day, stages=Stages(**out), counts={k: len(v) for k, v in out.items()})
