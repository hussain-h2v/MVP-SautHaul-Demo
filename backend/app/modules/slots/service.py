from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.appointments import service as appointments_service
from app.modules.appointments.models import ACTIVE_STATUSES
from app.modules.auth.deps import Principal
from app.modules.eta import service as eta_service
from app.modules.facilities import service as facilities_service
from app.modules.shipments import service as shipments_service
from app.modules.slots import repository
from app.modules.slots.models import AppointmentSlot
from app.modules.slots.schemas import (
    BulkStatusIn, BulkStatusOut, CopyDayIn, CopyDayOut, FacilityRef, GenerateIn, GenerateOut, GridAppointment,
    GridDock, GridEvent, GridSlot, PerDock, ScheduleOut, SlotDetail, SlotOut,
)

MAX_SLOTS_PER_REQUEST = 20000
EVENT_STATE = {"BREAKDOWN": "breakdown", "MAINTENANCE": "maintenance", "CAPACITY_REDUCTION": "reduced_capacity",
               "MANUAL_BLOCK": "blocked"}
APPT_STATE = {"PENDING_CONFIRMATION": "pending_confirmation", "CONFIRMED": "confirmed", "IN_PROGRESS": "in_progress",
              "COMPLETED": "completed"}


async def windows(db: AsyncSession, slot_ids: list[UUID]) -> dict[UUID, tuple[str, datetime, datetime]]:
    if not slot_ids:
        return {}
    rows = await db.execute(select(AppointmentSlot.id, AppointmentSlot.code, AppointmentSlot.slot_start_ts,
                                   AppointmentSlot.slot_end_ts).where(AppointmentSlot.id.in_(slot_ids)))
    return {i: (c, s, e) for i, c, s, e in rows.all()}


async def future_slot_ids(db: AsyncSession, dock_id: UUID, now: datetime) -> list[UUID]:
    rows = await db.execute(select(AppointmentSlot.id).where(AppointmentSlot.dock_id == dock_id,
                                                             AppointmentSlot.slot_end_ts > now))
    return [r[0] for r in rows.all()]


async def slot_ids_in_window(db: AsyncSession, dock_id: UUID, start: datetime, end: datetime | None) -> list[UUID]:
    stmt = select(AppointmentSlot.id).where(AppointmentSlot.dock_id == dock_id, AppointmentSlot.slot_end_ts > start)
    if end is not None:
        stmt = stmt.where(AppointmentSlot.slot_start_ts < end)
    return [r[0] for r in (await db.execute(stmt)).all()]


async def close_slots(db: AsyncSession, slot_ids: list[UUID], reason: str) -> None:
    if slot_ids:
        await db.execute(update(AppointmentSlot).where(AppointmentSlot.id.in_(slot_ids),
                                                       AppointmentSlot.slot_status == "OPEN")
                         .values(slot_status="CLOSED", block_reason=reason))


def _local_range(d: date, tz: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tz)
    start = datetime.combine(d, time(0), tzinfo=zone).astimezone(UTC)
    return start, start + timedelta(days=1)


def _overlaps(a: tuple[datetime, datetime], bs: list[tuple[datetime, datetime]]) -> bool:
    return any(a[0] < b[1] and b[0] < a[1] for b in bs)


def _slot_code(dock_code: str, start_local: datetime) -> str:
    return f"{dock_code}-{start_local:%y%m%d%H%M}"[-32:]


async def list_slots(db: AsyncSession, p: Principal, facility_id: UUID, date_from: date, date_to: date,
                     dock_id: UUID | None, status: str | None) -> list[SlotOut]:
    from app.modules.docks import service as docks_service

    fac = await facilities_service.get_in_scope(db, p, facility_id)
    if date_to < date_from or (date_to - date_from).days > 62:
        raise ValidationAppError("Choose a date range of at most 62 days")
    start = _local_range(date_from, fac.timezone)[0]
    end = _local_range(date_to, fac.timezone)[1]
    slots = await repository.list_slots(db, p, facility_id, start, end, dock_id, status)
    docks = await docks_service.by_ids(db, list({s.dock_id for s in slots}))
    booked = {a.slot_id for a in await appointments_service.active_for_slots(db, [s.id for s in slots])}
    return [SlotOut(id=s.id, code=s.code, dock_id=s.dock_id, dock_code=docks[s.dock_id].dock_code, start=s.slot_start_ts,
                    end=s.slot_end_ts, slot_status=s.slot_status, block_reason=s.block_reason, booked=s.id in booked)
            for s in slots]


async def dates(db: AsyncSession, p: Principal, facility_id: UUID) -> list[date]:
    fac = await facilities_service.get_in_scope(db, p, facility_id)
    return await repository.dates_with_slots(db, p, facility_id, fac.timezone)


async def _plan_windows(db: AsyncSession, p: Principal, facility_id: UUID, plan: list[tuple], tz: str,
                        lo: datetime, hi: datetime):
    """plan: [(dock, start_utc, end_utc)] -> (to_create, skipped_overlap) respecting existing slots and each other."""
    existing = await repository.existing_windows(db, list({d.id for d, _, _ in plan}), lo, hi)
    by_dock: dict[UUID, list[tuple[datetime, datetime]]] = {}
    for dock_id, s, e in existing:
        by_dock.setdefault(dock_id, []).append((s, e))
    create, skipped = [], 0
    for dock, s, e in plan:
        taken = by_dock.setdefault(dock.id, [])
        if _overlaps((s, e), taken):
            skipped += 1
            continue
        taken.append((s, e))
        create.append((dock, s, e))
    if len(create) > MAX_SLOTS_PER_REQUEST:
        raise ValidationAppError(f"That would create {len(create)} slots; the limit is {MAX_SLOTS_PER_REQUEST}")
    return create, skipped


async def generate(db: AsyncSession, p: Principal, body: GenerateIn) -> tuple[GenerateOut, list]:
    from app.modules.docks import service as docks_service

    fac = await facilities_service.get_in_scope(db, p, body.facility_id)
    zone = ZoneInfo(fac.timezone)
    docks = [d for d in await docks_service.list_docks(db, p, fac.id, "ACTIVE")]
    plan: list[tuple] = []
    d = body.date_from
    while d <= body.date_to:
        for t in body.templates:
            for dock in (x for x in docks if x.dock_type == t.dock_type):
                cur = datetime.combine(d, t.start, tzinfo=zone)
                limit = datetime.combine(d, t.end, tzinfo=zone)
                while cur + timedelta(minutes=t.length_min) <= limit:
                    nxt = cur + timedelta(minutes=t.length_min)
                    plan.append((dock, cur.astimezone(UTC), nxt.astimezone(UTC)))
                    cur = nxt
        d += timedelta(days=1)
    if len(plan) > MAX_SLOTS_PER_REQUEST * 2:
        raise ValidationAppError("Too many slots requested")
    lo, hi = _local_range(body.date_from, fac.timezone)[0], _local_range(body.date_to, fac.timezone)[1]
    create, skipped = await _plan_windows(db, p, fac.id, plan, fac.timezone, lo, hi)
    per: dict[str, int] = {}
    for dock, _, _ in create:
        per[dock.dock_code] = per.get(dock.dock_code, 0) + 1
    if not body.dry_run:
        for dock, s, e in create:
            db.add(AppointmentSlot(code=_slot_code(dock.code, s.astimezone(zone)), facility_id=fac.id, dock_id=dock.id,
                                   slot_start_ts=s, slot_end_ts=e))
        await db.flush()
    out = GenerateOut(dry_run=body.dry_run, to_create=len(create), skipped_overlap=skipped,
                      per_dock=[PerDock(dock_code=k, count=v) for k, v in sorted(per.items())])
    return out, create


async def bulk_status(db: AsyncSession, p: Principal, body: BulkStatusIn) -> BulkStatusOut:
    from app.modules.docks import service as docks_service

    slots = await repository.by_ids(db, p, body.slot_ids)
    if len(slots) != len(set(body.slot_ids)):
        raise NotFoundError("One or more slots were not found")
    affected = []
    if body.status != "OPEN":
        affected = await docks_service.affected_for_slots(db, [s.id for s in slots])
    if body.dry_run:
        return BulkStatusOut(applied=False, updated=0, affected_appointments=affected)
    if affected and not body.force:
        raise ConflictError("BOOKINGS_AFFECTED", "Some slots have active bookings",
                            {"affected_appointments": [a.model_dump(mode="json") for a in affected]})
    for s in slots:
        s.slot_status = body.status
        s.block_reason = None if body.status == "OPEN" else body.reason
    return BulkStatusOut(applied=True, updated=len(slots), affected_appointments=affected)


async def copy_day(db: AsyncSession, p: Principal, body: CopyDayIn) -> CopyDayOut:
    fac = await facilities_service.get_in_scope(db, p, body.facility_id)
    zone = ZoneInfo(fac.timezone)
    src_start, src_end = _local_range(body.from_date, fac.timezone)
    source = await repository.list_slots(db, p, fac.id, src_start, src_end)
    if not source:
        raise ValidationAppError("The source day has no slots to copy")
    from app.modules.docks import service as docks_service

    docks = await docks_service.by_ids(db, list({s.dock_id for s in source}))
    plan = []
    for target in sorted(set(body.to_dates)):
        if target == body.from_date:
            continue
        for s in source:
            ls, le = s.slot_start_ts.astimezone(zone), s.slot_end_ts.astimezone(zone)
            ns = datetime.combine(target, ls.timetz().replace(tzinfo=None), tzinfo=zone)
            ne = ns + (le - ls)
            plan.append((docks[s.dock_id], ns.astimezone(UTC), ne.astimezone(UTC)))
    lo = _local_range(min(body.to_dates), fac.timezone)[0]
    hi = _local_range(max(body.to_dates), fac.timezone)[1]
    create, skipped = await _plan_windows(db, p, fac.id, plan, fac.timezone, lo, hi)
    if not body.dry_run:
        for dock, s, e in create:
            db.add(AppointmentSlot(code=_slot_code(dock.code, s.astimezone(zone)), facility_id=fac.id, dock_id=dock.id,
                                   slot_start_ts=s, slot_end_ts=e))
        await db.flush()
    return CopyDayOut(dry_run=body.dry_run, to_create=len(create), skipped_overlap=skipped)


async def schedule(db: AsyncSession, p: Principal, facility_id: UUID, day: date) -> ScheduleOut:
    from app.modules.docks import service as docks_service

    fac = await facilities_service.get_in_scope(db, p, facility_id)
    start, end = _local_range(day, fac.timezone)
    docks = [d for d in await docks_service.list_docks(db, p, fac.id, None) if d.dock_status != "INACTIVE"]
    slots = await repository.list_slots(db, p, fac.id, start, end)
    appts = await appointments_service.for_slots(db, [s.id for s in slots])
    events = await docks_service.events_between(db, [d.id for d in docks], start, end)
    ships = await shipments_service.summaries(db, list({a.shipment_id for a in appts}))
    by_slot: dict[UUID, list] = {}
    for a in appts:
        by_slot.setdefault(a.slot_id, []).append(a)

    def grid_appt(a) -> GridAppointment:
        s = ships.get(a.shipment_id, {})
        return GridAppointment(id=a.id, code=a.code, status=a.appointment_status, shipment_code=s.get("code"),
                               carrier_name=s.get("carrier_name"), driver_name=s.get("driver_name"),
                               priority_code=s.get("priority_code"))

    out_docks = []
    for dock in docks:
        grid = []
        for s in [x for x in slots if x.dock_id == dock.id]:
            mine = by_slot.get(s.id, [])
            active = next((a for a in mine if a.appointment_status in ACTIVE_STATUSES), None)
            done = next((a for a in mine if a.appointment_status == "COMPLETED"), None)
            hist = [a for a in mine if a.appointment_status in ("CANCELLED", "REJECTED", "NO_SHOW")]
            ev = next((e for e in events if e.dock_id == dock.id and e.event_type in EVENT_STATE
                       and e.event_start_ts < s.slot_end_ts and (e.event_end_ts is None or e.event_end_ts > s.slot_start_ts)), None)
            appt = active or done
            history_state = None
            if hist:
                last = max(hist, key=lambda a: a.booked_at)
                history_state = "no_show" if last.appointment_status == "NO_SHOW" else "cancelled"
            if appt is not None and appt.appointment_status in ("COMPLETED", "IN_PROGRESS"):
                state = APPT_STATE[appt.appointment_status]
            elif ev is not None:
                state = EVENT_STATE[ev.event_type]
            elif s.slot_status != "OPEN":
                state = "blocked"
            elif appt is not None:
                state = APPT_STATE[appt.appointment_status]
            else:
                state = "open"
            grid.append(GridSlot(
                slot_id=s.id, code=s.code, start=s.slot_start_ts, end=s.slot_end_ts, state=state,
                block_reason=s.block_reason, history_state=history_state if state == "open" else None,
                event=GridEvent(event_type=ev.event_type, reason=ev.reason) if ev else None,
                appointment=grid_appt(appt) if appt else None,
            ))
        out_docks.append(GridDock(id=dock.id, code=dock.code, dock_code=dock.dock_code, dock_type=dock.dock_type,
                                  dock_status=dock.dock_status, slots=grid))
    return ScheduleOut(
        facility=FacilityRef(id=fac.id, code=fac.code, facility_name=fac.facility_name, timezone=fac.timezone,
                             open_time=fac.open_time, close_time=fac.close_time),
        date=day, docks=out_docks)


async def slot_detail(db: AsyncSession, p: Principal, slot_id: UUID) -> SlotDetail:
    from app.modules.docks import service as docks_service

    s = await repository.get_slot(db, p, slot_id)
    if s is None:
        raise NotFoundError("Slot not found")
    dock = (await docks_service.by_ids(db, [s.dock_id]))[s.dock_id]
    appts = await appointments_service.for_slots(db, [s.id])
    active = next((a for a in appts if a.appointment_status in ACTIVE_STATUSES), None)
    shown = active or next((a for a in reversed(appts) if a.appointment_status == "COMPLETED"), None)
    ships = await shipments_service.summaries(db, list({a.shipment_id for a in appts}))
    codes = {a.shipment_id: ships.get(a.shipment_id, {}).get("code") for a in appts}
    detail = dict(appointment=None, shipment=None, driver=None, vehicle=None, eta=None)
    if shown is not None:
        sh = ships.get(shown.shipment_id, {})
        eta = (await eta_service.latest_eta_for(db, [shown.shipment_id])).get(shown.shipment_id)
        detail = dict(
            appointment={"id": str(shown.id), "code": shown.code, "status": shown.appointment_status,
                         "booking_source": shown.booking_source, "booked_at": shown.booked_at,
                         "confirmed_at": shown.confirmed_at},
            shipment={"id": str(shown.shipment_id), **{k: sh.get(k) for k in (
                "code", "customer_name", "product_category", "load_weight_kg", "priority_code", "current_status",
                "required_dock_type", "expected_unload_min", "carrier_name")}},
            driver={"id": str(sh["driver_id"]) if sh.get("driver_id") else None, "name": sh.get("driver_name")},
            vehicle={"id": str(sh["vehicle_id"]) if sh.get("vehicle_id") else None},
            eta=eta,
        )
    history = [{"appointment_code": a.code, "shipment_code": codes.get(a.shipment_id), "status": a.appointment_status,
                "booked_at": a.booked_at, "cancelled_at": a.cancelled_at, "reason": a.cancellation_reason}
               for a in appts]
    return SlotDetail(
        slot=SlotOut(id=s.id, code=s.code, dock_id=s.dock_id, dock_code=dock.dock_code, start=s.slot_start_ts,
                     end=s.slot_end_ts, slot_status=s.slot_status, block_reason=s.block_reason, booked=active is not None),
        history=history, **detail)
