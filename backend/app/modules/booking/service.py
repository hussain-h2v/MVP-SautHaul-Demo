"""Appointment lifecycle and yard/gate operations (spec section 5, booking service).

M3 scope: planner confirmation of pending bookings, yard check-in, dock assignment, unloading,
gate-out and no-show. Holds, approvals and the full state machine are added in M4. No AI here."""
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.appointments import service as appointments_service
from app.modules.appointments.models import ACTIVE_STATUSES, Appointment, FacilityCheckin
from app.modules.auth.deps import Principal
from app.modules.booking import readers
from app.modules.booking.schemas import FinishOut, InboundRow, PendingOut, YardOut, YardRow
from app.modules.docks import service as docks_service
from app.modules.eta import service as eta_service
from app.modules.settings import service as settings_service
from app.modules.shipments import service as shipments_service

EARLY_MARGIN_MIN = 15  # earlier than this before slot start counts as EARLY
DEFAULT_GRACE_MIN = 30
AT_RISK_WINDOW_MIN = 30
WAITING = ("WAITING_EARLY", "WAITING_LATE", "WAITING_DOCK_UNAVAILABLE", "CALLED_TO_DOCK")


def now() -> datetime:
    return datetime.now(UTC)


def _min(a: datetime, b: datetime) -> int:
    return int((a - b).total_seconds() // 60)


def day_bounds(d: date, tz: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tz)
    start = datetime.combine(d, time.min, tzinfo=zone)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def local_today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


async def resolve_facility(db: AsyncSession, p: Principal, facility_id: UUID):
    f = await readers.get_facility(db, p, facility_id)
    if f is None:
        raise NotFoundError("Facility not found")
    return f


async def grace_minutes(db: AsyncSession, facility_id: UUID, on: date) -> int:
    v = await readers.rule_value(db, facility_id, "NO_SHOW_GRACE_MIN", on)
    if v is not None:
        return int(v)
    return int(await settings_service.get_value(db, "noshow_grace_minutes", DEFAULT_GRACE_MIN))


async def publish_change(facility_id: UUID, reason: str, **extra) -> None:
    try:
        await events.publish("schedule.changed", {"reason": reason, **extra}, facility_id=facility_id)
    except Exception:  # live updates are best-effort; the write already committed
        pass


async def _names(db: AsyncSession, shipments) -> tuple[dict, dict]:
    from app.modules.carriers import service as carriers_service
    from app.modules.drivers import service as drivers_service

    carriers = await carriers_service.names(db, list({s.carrier_id for s in shipments if s.carrier_id}))
    drivers = await drivers_service.names(db, list({s.driver_id for s in shipments if s.driver_id}))
    return carriers, drivers


# ---------------------------------------------------------------- pending confirmations
async def pending(db: AsyncSession, p: Principal, facility_id: UUID | None) -> list[PendingOut]:
    if facility_id:
        await resolve_facility(db, p, facility_id)
    rows = await readers.pending_appointments(db, p, facility_id)
    if not rows:
        return []
    shipments = await shipments_service.get_many(db, [a.shipment_id for a, _ in rows])
    carriers, drivers = await _names(db, list(shipments.values()))
    docks = await readers.docks_by_ids(db, list({s.dock_id for _, s in rows}))
    facilities = await readers.facilities_by_ids(db, list({s.facility_id for _, s in rows}))
    ttl = int(await settings_service.get_value(db, "pending_confirmation_ttl_minutes", 30))
    last_start: dict[UUID, time | None] = {}
    out = []
    for a, slot in rows:
        fac = facilities[slot.facility_id]
        if slot.facility_id not in last_start:
            v = await readers.rule_value(db, fac.id, "LAST_NEW_START_TIME", local_today(fac.timezone))
            last_start[fac.id] = time.fromisoformat(v) if v else None
        limit = last_start[fac.id]
        local_start = slot.slot_start_ts.astimezone(ZoneInfo(fac.timezone)).time()
        reason = "STARTS_AFTER_LAST_START" if limit and local_start > limit else "NEEDS_CONFIRMATION"
        s = shipments[a.shipment_id]
        out.append(PendingOut(
            appointment_id=a.id, code=a.code, shipment_id=s.id, shipment_code=s.code,
            carrier_name=carriers.get(s.carrier_id), driver_name=drivers.get(s.driver_id), priority_code=s.priority_code,
            slot_id=slot.id, slot_code=slot.code, dock_code=docks[slot.dock_id].dock_code,
            slot_start_ts=slot.slot_start_ts, slot_end_ts=slot.slot_end_ts, booked_at=a.booked_at,
            expires_at=a.booked_at + timedelta(minutes=ttl), reason=reason))
    return out


async def _scoped_appointment(db: AsyncSession, p: Principal, appointment_id: UUID):
    found = await readers.scoped_appointment(db, p, appointment_id)
    if found is None:
        raise NotFoundError("Appointment not found")
    return found


async def confirm(db: AsyncSession, p: Principal, appointment_id: UUID) -> tuple[Appointment, UUID]:
    a, slot = await _scoped_appointment(db, p, appointment_id)
    if a.appointment_status != "PENDING_CONFIRMATION":
        raise ConflictError("INVALID_STATE", f"Appointment is {a.appointment_status}, not pending confirmation")
    a.appointment_status, a.confirmed_at = "CONFIRMED", now()
    return a, slot.facility_id


async def reject(db: AsyncSession, p: Principal, appointment_id: UUID, reason: str) -> tuple[Appointment, UUID]:
    a, slot = await _scoped_appointment(db, p, appointment_id)
    if a.appointment_status != "PENDING_CONFIRMATION":
        raise ConflictError("INVALID_STATE", f"Appointment is {a.appointment_status}, not pending confirmation")
    a.appointment_status, a.is_current, a.cancellation_reason = "REJECTED", False, reason
    return a, slot.facility_id


# ---------------------------------------------------------------- lifecycle helpers (reused by M4)
def cancel(a: Appointment, reason: str) -> None:
    a.appointment_status, a.is_current, a.cancelled_at, a.cancellation_reason = "CANCELLED", False, now(), reason


def mark_no_show(a: Appointment) -> None:
    a.appointment_status, a.is_current = "NO_SHOW", False


# ---------------------------------------------------------------- yard row assembly
class _Ctx:
    pass


async def _context(db: AsyncSession, shipment_ids: list[UUID]) -> _Ctx:
    c = _Ctx()
    c.shipments = await shipments_service.get_many(db, shipment_ids)
    c.appts = await appointments_service.current_for_shipments(db, shipment_ids)
    c.checkins = await appointments_service.checkins_for_shipments(db, shipment_ids)
    c.slots = await readers.slots_by_ids(db, [a.slot_id for a in c.appts.values()])
    dock_ids = {s.dock_id for s in c.slots.values()} | {ck.actual_dock_id for ck in c.checkins.values() if ck.actual_dock_id}
    c.docks = await readers.docks_by_ids(db, list(dock_ids))
    c.etas = await eta_service.latest_eta_for(db, shipment_ids)
    c.carriers, c.drivers = await _names(db, list(c.shipments.values()))
    return c


def _row(c: _Ctx, sid: UUID, t: datetime) -> YardRow:
    s, a, ck = c.shipments[sid], c.appts.get(sid), c.checkins.get(sid)
    slot = c.slots.get(a.slot_id) if a else None
    planned = c.docks[slot.dock_id].dock_code if slot else None
    actual = c.docks[ck.actual_dock_id].dock_code if ck and ck.actual_dock_id else None
    waiting = 0
    if ck and ck.gate_in_ts:
        waiting = max(0, _min(ck.dock_in_ts or t, ck.gate_in_ts))
    overrun = None
    if ck and ck.unload_start_ts and ck.unload_end_ts:
        overrun = _min(ck.unload_end_ts, ck.unload_start_ts) - s.expected_unload_min
    return YardRow(
        shipment_id=s.id, shipment_code=s.code, carrier_name=c.carriers.get(s.carrier_id),
        driver_name=c.drivers.get(s.driver_id), priority_code=s.priority_code, load=s.required_dock_type,
        appointment_id=a.id if a else None, appointment_status=a.appointment_status if a else None,
        slot_code=slot.code if slot else None, planned_dock_code=planned, actual_dock_code=actual,
        slot_start_ts=slot.slot_start_ts if slot else None, slot_end_ts=slot.slot_end_ts if slot else None,
        eta_ts=(c.etas.get(sid) or {}).get("eta_ts"), gate_in_ts=ck.gate_in_ts if ck else None,
        queue_state=ck.queue_state if ck else None, queue_position=ck.queue_position if ck else None,
        waiting_min=waiting, arrival_state=ck.arrival_state if ck else None,
        unload_start_ts=ck.unload_start_ts if ck else None, unload_end_ts=ck.unload_end_ts if ck else None,
        overrun_min=overrun, dock_mismatch=bool(planned and actual and planned != actual),
        checkin_id=ck.id if ck else None)


async def yard(db: AsyncSession, p: Principal, facility_id: UUID, day: date | None) -> YardOut:
    fac = await resolve_facility(db, p, facility_id)
    day = day or local_today(fac.timezone)
    start, end = day_bounds(day, fac.timezone)
    checkins = await appointments_service.checkins_for_facility(db, fac.id)
    queue = [c for c in checkins if c.queue_state in WAITING]
    in_dock = [c for c in checkins if c.queue_state == "IN_DOCK"]
    done = [c for c in checkins if c.queue_state == "COMPLETED" and (c.unload_end_ts or c.gate_in_ts)
            and start <= (c.unload_end_ts or c.gate_in_ts) < end]
    checked = {c.shipment_id for c in checkins}
    expected = [a for a, _ in await readers.appointments_in_window(
        db, fac.id, start, end, ("PENDING_CONFIRMATION", "CONFIRMED")) if a.shipment_id not in checked]
    ids = [c.shipment_id for c in queue + in_dock + done] + [a.shipment_id for a in expected]
    ctx = await _context(db, ids)
    t = now()
    queue.sort(key=lambda c: (c.queue_position or 9999, c.gate_in_ts or t))
    in_dock.sort(key=lambda c: c.dock_in_ts or t)
    done.sort(key=lambda c: c.unload_end_ts or c.gate_in_ts, reverse=True)
    rows = [_row(ctx, a.shipment_id, t) for a in expected]
    rows.sort(key=lambda r: r.slot_start_ts or t)
    return YardOut(queue=[_row(ctx, c.shipment_id, t) for c in queue],
                   in_dock=[_row(ctx, c.shipment_id, t) for c in in_dock], expected=rows,
                   done=[_row(ctx, c.shipment_id, t) for c in done])


async def _row_for_shipment(db: AsyncSession, shipment_id: UUID) -> YardRow:
    return _row(await _context(db, [shipment_id]), shipment_id, now())


# ---------------------------------------------------------------- yard operations
async def check_in(db: AsyncSession, p: Principal, shipment_id: UUID) -> tuple[YardRow, UUID]:
    s = await shipments_service.get_scoped(db, p, shipment_id)
    fac = await resolve_facility(db, p, s.destination_facility_id)
    if s.current_status in ("CANCELLED", "COMPLETED"):
        raise ConflictError("INVALID_STATE", f"A {s.current_status} shipment cannot check in")
    if await appointments_service.checkin_for_shipment(db, s.id):
        raise ConflictError("ALREADY_CHECKED_IN", "This shipment has already checked in")
    t = now()
    appt = (await appointments_service.current_for_shipments(db, [s.id])).get(s.id)
    if appt is not None and appt.appointment_status not in ACTIVE_STATUSES:
        appt = None
    slot = (await readers.slots_by_ids(db, [appt.slot_id]))[appt.slot_id] if appt else None
    arrival, queue = None, "WAITING_DOCK_UNAVAILABLE"
    if slot:
        grace = await grace_minutes(db, fac.id, t.astimezone(ZoneInfo(fac.timezone)).date())
        if t < slot.slot_start_ts - timedelta(minutes=EARLY_MARGIN_MIN):
            arrival, queue = "EARLY", "WAITING_EARLY"
        elif t > slot.slot_start_ts + timedelta(minutes=grace):
            arrival, queue = "LATE", "WAITING_LATE"
        else:
            arrival = "ON_TIME"
            free = await appointments_service.dock_occupant(db, slot.dock_id) is None
            queue = "CALLED_TO_DOCK" if free else "WAITING_DOCK_UNAVAILABLE"
    position = await appointments_service.waiting_count(db, fac.id) + 1
    db.add(FacilityCheckin(shipment_id=s.id, facility_id=fac.id, gate_in_ts=t, yard_queue_enter_ts=t,
                           arrival_state=arrival, queue_state=queue, queue_position=position))
    await db.flush()
    await shipments_service.set_status(db, s.id, "AT_GATE" if queue == "CALLED_TO_DOCK" else "WAITING")
    return await _row_for_shipment(db, s.id), fac.id


async def _checkin(db: AsyncSession, p: Principal, checkin_id: UUID) -> FacilityCheckin:
    c = await appointments_service.get_checkin(db, checkin_id)
    if c is None or await readers.get_facility(db, p, c.facility_id) is None:
        raise NotFoundError("Check-in not found")
    return c


async def assign_dock(db: AsyncSession, p: Principal, checkin_id: UUID, dock_id: UUID) -> tuple[YardRow, UUID]:
    c = await _checkin(db, p, checkin_id)
    if c.queue_state in ("IN_DOCK", "COMPLETED") or c.gate_in_ts is None:
        raise ConflictError("INVALID_STATE", "This truck is not waiting for a dock")
    dock = (await readers.docks_by_ids(db, [dock_id])).get(dock_id)
    if dock is None or dock.facility_id != c.facility_id:
        raise ValidationAppError("Dock does not belong to this facility")
    s = (await shipments_service.get_many(db, [c.shipment_id]))[c.shipment_id]
    heavy = await readers.rule_value(db, c.facility_id, "HEAVY_DOCK_REQUIRED_KG", now().date())
    problems = docks_service.compatibility_problems(
        dock_type=dock.dock_type, dock_status=dock.dock_status, supports_refrigerated=dock.supports_refrigerated,
        max_weight_kg=dock.max_vehicle_weight_kg, required_dock_type=s.required_dock_type,
        temperature_control_required=s.temperature_control_required, load_weight_kg=s.load_weight_kg,
        heavy_required_kg=int(heavy) if heavy else None)
    if problems:
        raise ValidationAppError("Dock is not compatible with this load", {"problems": problems})
    if await appointments_service.dock_occupant(db, dock.id, exclude=c.id):
        raise ConflictError("DOCK_BUSY", "Another truck is still at this dock")
    c.actual_dock_id, c.dock_in_ts, c.queue_state, c.queue_position = dock.id, now(), "IN_DOCK", None
    await shipments_service.set_status(db, s.id, "IN_DOCK")
    return await _row_for_shipment(db, s.id), c.facility_id


async def start_unload(db: AsyncSession, p: Principal, checkin_id: UUID) -> tuple[YardRow, UUID]:
    c = await _checkin(db, p, checkin_id)
    if c.queue_state != "IN_DOCK" or c.unload_start_ts is not None:
        raise ConflictError("INVALID_STATE", "Truck must be at a dock and not yet unloading")
    c.unload_start_ts = now()
    appt = (await appointments_service.current_for_shipments(db, [c.shipment_id])).get(c.shipment_id)
    if appt and appt.appointment_status in ("PENDING_CONFIRMATION", "CONFIRMED"):
        appt.appointment_status = "IN_PROGRESS"
    return await _row_for_shipment(db, c.shipment_id), c.facility_id


async def finish_unload(db: AsyncSession, p: Principal, checkin_id: UUID) -> tuple[FinishOut, UUID]:
    c = await _checkin(db, p, checkin_id)
    if c.unload_start_ts is None or c.unload_end_ts is not None:
        raise ConflictError("INVALID_STATE", "Unloading has not started or is already finished")
    c.unload_end_ts, c.queue_state, c.queue_position = now(), "COMPLETED", None
    appt = (await appointments_service.current_for_shipments(db, [c.shipment_id])).get(c.shipment_id)
    if appt and appt.appointment_status in ACTIVE_STATUSES:
        appt.appointment_status = "COMPLETED"
    await shipments_service.set_status(db, c.shipment_id, "COMPLETED")
    row = await _row_for_shipment(db, c.shipment_id)
    unload = _min(c.unload_end_ts, c.unload_start_ts)
    detention = max(0, _min(c.unload_start_ts, c.gate_in_ts)) if c.gate_in_ts else 0
    return FinishOut(**row.model_dump(), unload_min=unload, detention_min=detention), c.facility_id


async def gate_out(db: AsyncSession, p: Principal, checkin_id: UUID) -> tuple[YardRow, UUID]:
    c = await _checkin(db, p, checkin_id)
    if c.queue_state != "COMPLETED" or c.gate_out_ts is not None:
        raise ConflictError("INVALID_STATE", "Unloading must be finished and the truck not yet gated out")
    c.gate_out_ts = now()
    return await _row_for_shipment(db, c.shipment_id), c.facility_id


async def no_show(db: AsyncSession, p: Principal, appointment_id: UUID) -> tuple[Appointment, UUID]:
    a, slot = await _scoped_appointment(db, p, appointment_id)
    if a.appointment_status not in ("PENDING_CONFIRMATION", "CONFIRMED"):
        raise ConflictError("INVALID_STATE", f"A {a.appointment_status} appointment cannot be marked no-show")
    fac = await resolve_facility(db, p, slot.facility_id)
    grace = await grace_minutes(db, fac.id, slot.slot_start_ts.astimezone(ZoneInfo(fac.timezone)).date())
    if now() <= slot.slot_start_ts + timedelta(minutes=grace):
        raise ConflictError("GRACE_NOT_ELAPSED", f"The {grace}-minute grace period has not elapsed",
                            {"grace_minutes": grace})
    mark_no_show(a)
    ck = (await appointments_service.checkins_for_shipments(db, [a.shipment_id])).get(a.shipment_id)
    if ck:
        ck.arrival_state = "NO_SHOW"
    return a, fac.id


# ---------------------------------------------------------------- inbound trucks
async def inbound(db: AsyncSession, p: Principal, facility_id: UUID, day: date | None) -> list[InboundRow]:
    fac = await resolve_facility(db, p, facility_id)
    day = day or local_today(fac.timezone)
    start, end = day_bounds(day, fac.timezone)
    ships = await shipments_service.inbound_for_facility(db, fac.id)
    ctx = await _context(db, [s.id for s in ships])
    out = []
    for s in ships:
        a = ctx.appts.get(s.id)
        if a is not None and a.appointment_status not in ACTIVE_STATUSES:
            a = None
        slot = ctx.slots.get(a.slot_id) if a else None
        eta = ctx.etas.get(s.id) or {}
        eta_ts = eta.get("eta_ts")
        if not ((eta_ts and start <= eta_ts < end) or (slot and start <= slot.slot_start_ts < end)):
            continue
        late = bool(eta_ts and slot and eta_ts > slot.slot_start_ts)
        at_risk = not late and (
            slot is None or eta.get("eta_confidence") == "LOW" or eta_ts is None
            or slot.slot_start_ts - eta_ts <= timedelta(minutes=AT_RISK_WINDOW_MIN))
        out.append(InboundRow(
            shipment_id=s.id, shipment_code=s.code, carrier_name=ctx.carriers.get(s.carrier_id),
            driver_name=ctx.drivers.get(s.driver_id), priority_code=s.priority_code,
            required_dock_type=s.required_dock_type, current_status=s.current_status, eta_ts=eta_ts,
            eta_source=eta.get("eta_source"), eta_confidence=eta.get("eta_confidence"),
            appointment_id=a.id if a else None, appointment_status=a.appointment_status if a else None,
            slot_code=slot.code if slot else None,
            dock_code=ctx.docks[slot.dock_id].dock_code if slot else None,
            slot_start_ts=slot.slot_start_ts if slot else None, late=late, at_risk=at_risk))
    out.sort(key=lambda r: r.eta_ts or end)
    return out


async def yard_counts(db: AsyncSession, facility_id: UUID) -> int:
    cks = await appointments_service.checkins_for_facility(db, facility_id)
    return sum(1 for c in cks if c.queue_state in WAITING or c.queue_state == "IN_DOCK")


async def pending_count(db: AsyncSession, p: Principal, facility_id: UUID) -> int:
    return len(await readers.pending_appointments(db, p, facility_id))
