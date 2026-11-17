"""Request detail for the coordinator: everything needed to decide in one read, plus the rule-based recommendation
and the escalate action. Decisions themselves (approve / suggest / hold / reject) live in modules/booking/engine."""
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.appointments import service as appointments_service
from app.modules.appointments.models import ACTIVE_STATUSES
from app.modules.booking import engine, readers
from app.modules.booking.models import ApprovalRequest, SlotHold
from app.modules.coordinator import locks, messaging
from app.modules.coordinator.recommend import HeldFacts, OptionFacts, recommend
from app.modules.drivers import service as drivers_service
from app.modules.eta import service as eta_service
from app.modules.exceptions import service as exceptions_service
from app.modules.scheduling import service as scheduling
from app.modules.scheduling.router import to_out
from app.modules.shipments import service as shipments_service
from app.modules.whatsapp import service as whatsapp_service


async def get_request(db: AsyncSession, request_id: UUID) -> ApprovalRequest:
    r = await db.get(ApprovalRequest, request_id)
    if r is None:
        raise NotFoundError("Request not found")
    return r


async def _slot_info(db: AsyncSession, slot_ids: list[UUID]):
    slots = await readers.slots_by_ids(db, slot_ids)
    docks = await readers.docks_by_ids(db, list({s.dock_id for s in slots.values()}))
    return slots, docks


async def detail(db: AsyncSession, redis: Redis, request_id: UUID, now: datetime | None = None) -> dict:
    from app.modules.carriers import service as carriers_service

    now = now or datetime.now(UTC)
    r = await get_request(db, request_id)
    s = (await shipments_service.get_many(db, [r.shipment_id]))[r.shipment_id]
    fac = (await readers.facilities_by_ids(db, [s.destination_facility_id]))[s.destination_facility_id]
    carriers = await carriers_service.names(db, [s.carrier_id] if s.carrier_id else [])
    driver = (await drivers_service.get_many(db, [s.driver_id])).get(s.driver_id) if s.driver_id else None

    appt = (await appointments_service.current_for_shipments(db, [s.id])).get(s.id)
    current = None
    if appt is not None and appt.appointment_status in ACTIVE_STATUSES:
        slots, docks = await _slot_info(db, [appt.slot_id])
        sl = slots[appt.slot_id]
        current = {"id": appt.id, "status": appt.appointment_status, "slot_code": sl.code, "dock_code": docks[sl.dock_id].dock_code,
                   "start": sl.slot_start_ts, "end": sl.slot_end_ts}

    eta = await eta_service.effective_eta(db, s.id)
    history = [{"created_at": u.created_at, "declared_eta_ts": u.declared_eta_ts, "upper_ts": u.declared_eta_upper_ts,
                "source": u.source_type, "confidence": u.confidence_code, "reason": u.delay_reason_code, "note": u.note}
               for u in await eta_service.history(db, s.id)]

    exc = await exceptions_service.get_exception(db, r.exception_id) if r.exception_id else None
    facts = None
    if exc is not None:
        msg = await whatsapp_service.latest_driver_message(db, exc.thread_id)
        facts = {"exception_id": exc.id, "reason": exc.exception_type, "reported_delay_min": exc.reported_delay_min,
                 "declared_eta_ts": exc.declared_eta_ts, "earliest_acceptable_ts": exc.earliest_acceptable_ts,
                 "latest_acceptable_ts": exc.latest_acceptable_ts, "description": exc.description,
                 "original_message": msg.message_text if msg else None, "translation": None,
                 "confidence": None, "requires_human_review": bool(msg.requires_human_review) if msg else False}

    held_option, held_facts = None, None
    hold = await db.get(SlotHold, r.hold_id) if r.hold_id else None
    if hold is not None:
        ctx = await scheduling.load_context(db, s.id)
        slot_ids = hold.all_slot_ids
        check = await scheduling.check_run(db, ctx, slot_ids, now, ignore_hold_ids=(hold.id,))
        slots, docks = await _slot_info(db, slot_ids)
        first = slots[slot_ids[0]]
        expired = hold.status != "active" or hold.expires_at <= now
        held_option = {"hold_id": hold.id, "slot_ids": slot_ids, "slot_codes": [slots[i].code for i in slot_ids],
                       "dock_code": docks[first.dock_id].dock_code, "start": first.slot_start_ts, "end": slots[slot_ids[-1]].slot_end_ts,
                       "expires_at": hold.expires_at, "seconds_left": 0 if expired else int((hold.expires_at - now).total_seconds()),
                       "feasible": not check.problems and not expired, "problems": check.problems, "status": hold.status}
        held_facts = HeldFacts(feasible=not check.problems and not expired, needs_planner_approval=check.needs_planner_approval,
                               problems=check.problems, start=first.slot_start_ts, slot_code=first.code, expired=expired)

    res = await scheduling.find_options(db, s.id, effective_eta=(exc.declared_eta_ts if exc and exc.declared_eta_ts else None),
                                        latest_finish=exc.latest_acceptable_ts if exc else None, limit=5)
    options = to_out(s.id, res).options
    rec = recommend(
        held=held_facts, options=[OptionFacts(o.slot_ids, o.slot_codes, o.start, o.needs_planner_approval) for o in options],
        eta_ts=eta.ts if eta else None, eta_confidence=eta.confidence if eta else None, eta_range=bool(eta and eta.upper_ts),
        requires_human_review=bool(eta and eta.requires_human_review) or bool(facts and facts["requires_human_review"]),
        priority=s.priority_code, replan=(r.reason_code or "").startswith("REPLAN"),
        current_slot_code=current["slot_code"] if current else None, now=now)
    return {
        "request": {"id": r.id, "status": r.status, "reason_code": r.reason_code, "created_at": r.created_at,
                    "decision_deadline": r.decision_deadline, "reason": r.reason, "hold_id": r.hold_id},
        "shipment": {"id": s.id, "code": s.code, "priority_code": s.priority_code, "required_dock_type": s.required_dock_type,
                     "load_weight_kg": s.load_weight_kg, "expected_unload_min": s.expected_unload_min,
                     "temperature_control_required": s.temperature_control_required, "carrier_name": carriers.get(s.carrier_id),
                     "driver_name": driver.driver_name if driver else None,
                     "driver_language": driver.preferred_language if driver else None,
                     "driver_phone": (driver.whatsapp_number or driver.phone) if driver else None},
        "facility": {"id": fac.id, "code": fac.code, "name": fac.facility_name},
        "current_appointment": current,
        "eta": {"ts": eta.ts, "source": eta.source, "confidence": eta.confidence, "upper_ts": eta.upper_ts,
                "requires_human_review": eta.requires_human_review} if eta else None,
        "eta_history": history, "facts": facts, "held_option": held_option,
        "options": [o.model_dump() for o in options],
        "recommendation": {"action": rec.action, "slot_ids": rec.slot_ids, "reasons": rec.reasons, "impact": rec.impact,
                           "risk_flags": rec.risk_flags, "source": rec.source},
        "claimed_by": await locks.owner_of(redis, "request", request_id),
    }


async def escalate(db: AsyncSession, request_id: UUID, user_id: UUID, reason: str, note: str | None, now: datetime | None = None):
    """The coordinator decides no safe automatic outcome exists: release any hold, keep the current booking, open an
    escalation with a hand-off record, tell the driver a person will follow up."""
    now = now or datetime.now(UTC)
    r = await get_request(db, request_id)
    if r.status not in ("waiting", "held", "suggested"):
        raise ConflictError("REQUEST_CLOSED", f"This request is already {r.status}")
    if r.hold_id is not None:
        await engine.release_hold(db, r.hold_id, reason="escalated")
    s = (await shipments_service.get_many(db, [r.shipment_id]))[r.shipment_id]
    eta = await eta_service.effective_eta(db, s.id)
    appt = (await appointments_service.current_for_shipments(db, [s.id])).get(s.id)
    esc = await engine.escalate(db, s.id, "COORDINATOR_ESCALATION", {
        "summary": reason, "note": note, "escalated_by": str(user_id), "request_id": str(r.id), "request_reason_code": r.reason_code,
        "shipment": {"code": s.code, "priority": s.priority_code, "required_dock_type": s.required_dock_type,
                     "load_weight_kg": s.load_weight_kg, "expected_unload_min": s.expected_unload_min},
        "eta": {"ts": eta.ts.isoformat(), "source": eta.source, "confidence": eta.confidence} if eta else None,
        "current_appointment": {"id": str(appt.id), "status": appt.appointment_status} if appt and appt.appointment_status in ACTIVE_STATUSES else None},
        exception_id=r.exception_id)
    r.status, r.decided_by, r.decided_at, r.reason = "escalated", user_id, now, reason
    await messaging.to_driver(db, s.id, "escalation_notice", {"reference": esc.id and str(esc.id)[:8]})
    return esc
