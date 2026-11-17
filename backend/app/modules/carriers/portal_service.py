from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationAppError
from app.modules.auth.deps import Principal
from app.modules.carriers import portal_repository as repo
from app.modules.carriers.portal_schemas import (
    AppointmentRef, CarrierReport, CheckinRef, DashboardOut, DriverRef, EscalationRef, EtaRef, FacilityRef, LoadOut,
    SlotChange, TrackerPage, TrackerRow, VehicleRef,
)
from app.modules.eta import service as eta_service
from app.modules.slots import service as slots_service

TZ = ZoneInfo("Asia/Kolkata")
DECLARED_BY = {"DRIVER_DECLARED": "driver", "OPERATIONS_OVERRIDE": "operations", "WAREHOUSE_ESTIMATE": "warehouse",
               "ORIGINAL_PLAN": "plan"}
REPORT_KINDS = ("shipments", "delays", "detention")


def resolve_carrier(p: Principal, requested: UUID | None) -> UUID | None:
    """A carrier user is always pinned to their own carrier; asking for another one is a 404, never a leak."""
    if p.role == "carrier_user":
        if requested is not None and requested != p.carrier_id:
            raise NotFoundError("Carrier not found")
        return p.carrier_id
    return requested


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=TZ)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


async def dashboard(db: AsyncSession, p: Principal, carrier_id: UUID | None) -> DashboardOut:
    now = datetime.now(UTC)
    today = datetime.now(TZ).date()
    start, end = _day_bounds(today)
    counts = await repo.dashboard_counts(db, p, carrier_id, start, end, now - timedelta(days=30))
    risk = await repo.at_risk_appointments(db, p, carrier_id)
    etas = await eta_service.latest_eta_for(db, [sid for sid, _ in risk])
    late = sum(1 for sid, slot_start in risk if (etas.get(sid) or {}).get("eta_ts") and etas[sid]["eta_ts"] > slot_start)
    return DashboardOut(late_trucks=late, **counts)


async def tracker(db: AsyncSession, p: Principal, carrier_id: UUID | None, q, status, facility_id, driver_id,
                  limit: int, offset: int) -> TrackerPage:
    now = datetime.now(UTC)
    total, ships = await repo.tracker_page(db, p, carrier_id, q, status, facility_id, driver_id, limit, offset)
    ctx = await repo.tracker_context(db, list(ships), now)
    etas = await eta_service.latest_eta_for(db, [s.id for s in ships])
    items = []
    for s in ships:
        veh, drv, fac = ctx["vehicles"].get(s.vehicle_id), ctx["drivers"].get(s.driver_id), ctx["facilities"][s.destination_facility_id]
        appt = ctx["appts"].get(s.id)
        ck = ctx["checkins"].get(s.id)
        esc = ctx["escalations"].get(s.id)
        e = etas.get(s.id) or {}
        req = ctx["requests"].get(s.id)
        if req == "suggested":
            hold_state = "request_suggested"
        elif req in ("waiting", "held"):
            hold_state = "request_waiting"
        elif appt and appt[0].appointment_status == "PENDING_CONFIRMATION":
            hold_state = "pending_confirmation"
        elif s.id in ctx["holds"]:
            hold_state = "held"
        else:
            hold_state = "none"
        items.append(TrackerRow(
            shipment_id=s.id, code=s.code, order_reference=s.order_reference, current_status=s.current_status,
            load=LoadOut(required_dock_type=s.required_dock_type, temperature_control_required=s.temperature_control_required,
                         weight_kg=s.load_weight_kg),
            vehicle=VehicleRef(id=veh.id, registration_number=veh.registration_number) if veh else None,
            driver=DriverRef(id=drv.id, name=drv.driver_name, language=drv.preferred_language) if drv else None,
            facility=FacilityRef(id=fac.id, code=fac.code, name=fac.facility_name),
            appointment=AppointmentRef(id=appt[0].id, status=appt[0].appointment_status, slot_code=appt[1].code,
                                       dock_code=appt[2].dock_code, start=appt[1].slot_start_ts, end=appt[1].slot_end_ts) if appt else None,
            eta=EtaRef(ts=e.get("eta_ts"), source=e.get("eta_source"), confidence=e.get("eta_confidence"),
                       declared_by=DECLARED_BY.get(e.get("eta_source") or "ORIGINAL_PLAN", "plan")),
            checkin=CheckinRef(arrival_state=ck.arrival_state, gate_in_ts=ck.gate_in_ts, queue_state=ck.queue_state) if ck else None,
            hold_state=hold_state, escalation=EscalationRef(status=esc.status, reason_code=esc.reason_code) if esc else None))
    return TrackerPage(total=total, items=items)


async def slot_changes(db: AsyncSession, p: Principal, carrier_id: UUID | None, limit: int) -> list[SlotChange]:
    from app.modules.shipments import service as shipments_service

    appts, holds, reqs, escs = await repo.slot_change_sources(db, p, carrier_id, limit)
    ship_ids = {x.shipment_id for x in [*appts, *holds, *reqs, *escs] if x.shipment_id}
    ships = await shipments_service.get_many(db, list(ship_ids))
    slot_ids = {a.slot_id for a in appts} | {h.slot_id for h in holds} | {r.suggested_slot_id or r.slot_id for r in reqs if (r.suggested_slot_id or r.slot_id)}
    windows = await slots_service.windows(db, list(slot_ids))

    def slot(sid):
        w = windows.get(sid)
        return (w[0], w[1]) if w else (None, None)

    out: list[SlotChange] = []

    def add(ts, shipment_id, kind, reason, slot_id):
        s = ships.get(shipment_id)
        code, start = slot(slot_id) if slot_id else (None, None)
        out.append(SlotChange(ts=ts, shipment_id=shipment_id, shipment_code=s.code if s else "?", kind=kind, reason=reason,
                              slot_code=code, start=start))

    for a in appts:
        st = a.appointment_status
        if st == "CONFIRMED":
            add(a.confirmed_at or a.booked_at, a.shipment_id, "confirmed", None, a.slot_id)
        elif st == "PENDING_CONFIRMATION":
            add(a.booked_at, a.shipment_id, "pending_confirmation", "Waiting for the planner to confirm", a.slot_id)
        elif st == "CANCELLED":
            kind = "replaced" if a.cancellation_reason == "REPLACED" else "cancelled"
            add(a.cancelled_at or a.updated_at, a.shipment_id, kind, a.cancellation_reason, a.slot_id)
        elif st == "REJECTED":
            add(a.cancelled_at or a.updated_at, a.shipment_id, "rejected", a.cancellation_reason, a.slot_id)
        elif st == "NO_SHOW":
            add(a.updated_at, a.shipment_id, "no_show", None, a.slot_id)
    for h in holds:
        add(h.created_at, h.shipment_id, "held", f"Held until {h.expires_at.astimezone(TZ).strftime('%H:%M')}", h.slot_id)
    for r in reqs:
        kind = {"suggested": "suggested", "rejected": "rejected", "held": "held"}[r.status]
        add(r.decided_at or r.updated_at, r.shipment_id, kind, r.reason, r.suggested_slot_id or r.slot_id)
    for e in escs:
        add(e.created_at, e.shipment_id, "escalated", e.handoff_record.get("summary") or e.reason_code, None)
    out.sort(key=lambda c: c.ts, reverse=True)
    return out[:limit]


async def report(db: AsyncSession, p: Principal, carrier_id: UUID | None, kind: str, date_from: date, date_to: date) -> CarrierReport:
    if kind not in REPORT_KINDS:
        raise ValidationAppError("Unknown report kind", {"allowed": list(REPORT_KINDS)})
    if date_to < date_from or (date_to - date_from).days > 366:
        raise ValidationAppError("Choose a date range of at most one year")
    start, end = _day_bounds(date_from)[0], _day_bounds(date_to)[1]
    if kind == "detention":
        rows = await repo.report_detention(db, p, carrier_id, start, end)
        fac = await repo.facility_codes(db, list({s.destination_facility_id for s, _ in rows}))
        data = [{"shipment": s.code, "facility": fac.get(s.destination_facility_id), "gate_in": c.gate_in_ts.isoformat(),
                 "unload_start": c.unload_start_ts.isoformat(),
                 "detention_min": int((c.unload_start_ts - c.gate_in_ts).total_seconds() // 60)} for s, c in rows]
        return CarrierReport(kind=kind, columns=["shipment", "facility", "gate_in", "unload_start", "detention_min"], rows=data)
    ships = await repo.report_shipments(db, p, carrier_id, start, end)
    fac = await repo.facility_codes(db, list({s.destination_facility_id for s in ships}))
    if kind == "shipments":
        data = [{"shipment": s.code, "order_reference": s.order_reference, "facility": fac.get(s.destination_facility_id),
                 "status": s.current_status, "priority": s.priority_code, "load_type": s.required_dock_type,
                 "weight_kg": s.load_weight_kg, "planned_eta": s.original_eta_ts.isoformat()} for s in ships]
        return CarrierReport(kind=kind, columns=list(data[0]) if data else
                             ["shipment", "order_reference", "facility", "status", "priority", "load_type", "weight_kg", "planned_eta"],
                             rows=data)
    etas = await eta_service.latest_eta_for(db, [s.id for s in ships])
    data = []
    for s in ships:
        eta = (etas.get(s.id) or {}).get("eta_ts") or s.original_eta_ts
        data.append({"shipment": s.code, "facility": fac.get(s.destination_facility_id), "planned_eta": s.original_eta_ts.isoformat(),
                     "latest_eta": eta.isoformat(), "delay_min": int((eta - s.original_eta_ts).total_seconds() // 60),
                     "eta_source": (etas.get(s.id) or {}).get("eta_source", "ORIGINAL_PLAN")})
    return CarrierReport(kind=kind, columns=["shipment", "facility", "planned_eta", "latest_eta", "delay_min", "eta_source"], rows=data)
