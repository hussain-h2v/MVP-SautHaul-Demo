"""Booking service: every capacity write (hold, approve, suggest, reject, expire, move, cancel).

Rules (spec section 5):
* Showing an option never reserves. A hold is time-limited and not a promise. Only CONFIRMED is a promise.
* place_hold locks the slot rows (SELECT ... FOR UPDATE, id order), re-validates feasibility, then inserts the
  hold and its slot_claims. Concurrent callers for the same slot get SLOT_TAKEN. PostgreSQL is the backstop:
  partial unique indexes on active holds / claims / appointments make a double allocation impossible.
* No AI runs here; AI only reads and recommends, then calls these functions through typed tools."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.errors import ConflictError, NotFoundError, SlotTakenError, SlotUnavailableError, ValidationAppError
from app.modules.appointments.models import ACTIVE_STATUSES, Appointment
from app.modules.booking import readers
from app.modules.booking.models import ApprovalRequest, Escalation, SlotClaim, SlotHold
from app.modules.notifications.models import OutboxEvent
from app.modules.scheduling import service as scheduling
from app.modules.settings import service as settings_service
from app.modules.shipments import service as shipments_service
from app.modules.shipments.models import Shipment

MAX_WINDOWS = 3
MAX_HOLD_MINUTES = 60
SOURCES = ("PLANNER", "DRIVER_CHAT", "WAREHOUSE", "SCHEDULING_TOOL", "MANUAL_OVERRIDE")


def _now() -> datetime:
    return datetime.now(UTC)


def emit(db: AsyncSession, event_type: str, payload: dict) -> None:
    """Outbox: written in the same transaction as the state change; a worker delivers it later."""
    db.add(OutboxEvent(event_type=event_type, payload={k: (str(v) if isinstance(v, UUID) else v) for k, v in payload.items()}))


async def _ttl(db: AsyncSession, key: str, default: int) -> int:
    return int(await settings_service.get_value(db, key, default))


# ---------------------------------------------------------------- claims
async def _release_claims(db: AsyncSession, *, hold_id: UUID | None = None, appointment_id: UUID | None = None) -> None:
    stmt = update(SlotClaim).where(SlotClaim.active.is_(True))
    stmt = stmt.where(SlotClaim.hold_id == hold_id) if hold_id else stmt.where(SlotClaim.appointment_id == appointment_id)
    await db.execute(stmt.values(active=False))


async def release_appointment_claims(db: AsyncSession, appointment_id: UUID) -> None:
    await _release_claims(db, appointment_id=appointment_id)


async def _close_hold(db: AsyncSession, hold: SlotHold, status: str) -> None:
    hold.status = status
    await _release_claims(db, hold_id=hold.id)
    await db.flush()


async def _active_hold(db: AsyncSession, shipment_id: UUID) -> SlotHold | None:
    return (await db.execute(select(SlotHold).where(SlotHold.shipment_id == shipment_id, SlotHold.status == "active")
                             .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def _expire_stale_for(db: AsyncSession, slot_ids: list[UUID], now: datetime) -> None:
    rows = (await db.execute(
        select(SlotHold).join(SlotClaim, SlotClaim.hold_id == SlotHold.id)
        .where(SlotClaim.slot_id.in_(slot_ids), SlotClaim.active.is_(True), SlotHold.status == "active",
               SlotHold.expires_at <= now).distinct())).scalars().all()
    for h in rows:
        await _close_hold(db, h, "expired")
        metrics.HOLDS.labels("expired").inc()
        emit(db, "hold.expired", {"shipment_id": h.shipment_id, "hold_id": h.id})


async def claimed_slot_ids(db: AsyncSession, appointment_id: UUID) -> list[UUID]:
    rows = await db.execute(select(SlotClaim.slot_id).where(SlotClaim.appointment_id == appointment_id,
                                                            SlotClaim.active.is_(True)))
    return [r[0] for r in rows.all()]


async def appointment_for_hold(db: AsyncSession, hold_id: UUID) -> Appointment | None:
    row = (await db.execute(select(SlotClaim.appointment_id).where(SlotClaim.hold_id.is_(None)).where(
        SlotClaim.slot_id == (select(SlotHold.slot_id).where(SlotHold.id == hold_id).scalar_subquery()),
        SlotClaim.appointment_id.is_not(None)).order_by(SlotClaim.created_at.desc()).limit(1))).first()
    return await db.get(Appointment, row[0]) if row else None


# ---------------------------------------------------------------- hold
async def place_hold(db: AsyncSession, shipment_id: UUID, slot_ids: list[UUID], *, exception_id: UUID | None = None,
                     now: datetime | None = None, ttl_minutes: int | None = None, check_eta: bool = True) -> SlotHold:
    """Reserve (not promise) an option. One transaction: lock -> re-validate -> insert. Raises SLOT_TAKEN when another
    request got there first, SLOT_UNAVAILABLE when the option stopped being feasible."""
    now = now or _now()
    slot_ids = list(dict.fromkeys(slot_ids))
    if not slot_ids or len(slot_ids) > MAX_WINDOWS:
        raise ValidationAppError(f"Choose between 1 and {MAX_WINDOWS} consecutive slots")
    slots = await readers.lock_slots(db, slot_ids)
    if len(slots) != len(slot_ids):
        raise NotFoundError("One or more slots were not found")
    shipment = (await db.execute(select(Shipment).where(Shipment.id == shipment_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if shipment is None:
        raise NotFoundError("Shipment not found")
    if shipment.current_status in ("CANCELLED", "COMPLETED"):
        raise ConflictError("SHIPMENT_CLOSED", f"A {shipment.current_status} shipment cannot hold a slot")
    existing = await _active_hold(db, shipment_id)
    if existing is not None and set(existing.all_slot_ids) == set(slot_ids) and existing.expires_at > now:
        return existing  # idempotent retry of the same request
    await _expire_stale_for(db, slot_ids, now)
    own = (existing.id,) if existing is not None else ()
    taken = await readers.occupied_slot_ids(db, slot_ids, now, ignore_hold_ids=own)
    if taken:
        metrics.SLOT_TAKEN.inc()
        metrics.HOLDS.labels("slot_taken").inc()
        raise SlotTakenError(str(sorted(taken, key=str)[0]))
    ctx = await scheduling.load_context(db, shipment_id)
    check = await scheduling.check_run(db, ctx, slot_ids, now, check_eta=check_eta, ignore_hold_ids=own)
    if check.problems:
        metrics.INFEASIBLE_AT_REVALIDATION.inc()
        metrics.HOLDS.labels("unavailable").inc()
        raise SlotUnavailableError(check.problems)
    if existing is not None:
        await _close_hold(db, existing, "released")  # a shipment holds one slot at a time
    ttl = ttl_minutes or await _ttl(db, "hold_ttl_minutes", 15)
    ordered = sorted(slots, key=lambda s: s.slot_start_ts)
    hold = SlotHold(shipment_id=shipment_id, slot_id=ordered[0].id, extra_slot_ids=[str(s.id) for s in ordered[1:]],
                    requested_exception_id=exception_id, status="active", expires_at=now + timedelta(minutes=ttl))
    try:
        async with db.begin_nested():
            db.add(hold)
            await db.flush()
            for s in ordered:
                db.add(SlotClaim(slot_id=s.id, hold_id=hold.id, active=True))
            await db.flush()
    except IntegrityError:
        metrics.SLOT_TAKEN.inc()
        metrics.HOLDS.labels("slot_taken").inc()
        raise SlotTakenError(str(ordered[0].id)) from None
    metrics.HOLDS.labels("placed").inc()
    emit(db, "hold.placed", {"shipment_id": shipment_id, "hold_id": hold.id, "expires_at": hold.expires_at.isoformat()})
    return hold


async def release_hold(db: AsyncSession, hold_id: UUID, *, reason: str = "released") -> SlotHold:
    hold = (await db.execute(select(SlotHold).where(SlotHold.id == hold_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if hold is None:
        raise NotFoundError("Hold not found")
    if hold.status != "active":
        return hold
    await _close_hold(db, hold, "released")
    metrics.HOLDS.labels("released").inc()
    emit(db, "hold.released", {"shipment_id": hold.shipment_id, "hold_id": hold.id, "reason": reason})
    return hold


# ---------------------------------------------------------------- appointment creation
_NEXT_CODE = text("SELECT nextval('appointment_code_seq')")


async def _next_code(db: AsyncSession) -> str:
    return f"APT{(await db.execute(_NEXT_CODE)).scalar_one()}"


async def _current_active(db: AsyncSession, shipment_id: UUID) -> Appointment | None:
    return (await db.execute(select(Appointment).where(
        Appointment.shipment_id == shipment_id, Appointment.is_current.is_(True),
        Appointment.appointment_status.in_(ACTIVE_STATUSES)).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def _replace(db: AsyncSession, old: Appointment, reason: str, now: datetime) -> None:
    old.appointment_status, old.is_current, old.cancelled_at, old.cancellation_reason = "CANCELLED", False, now, reason
    await _release_claims(db, appointment_id=old.id)
    await db.flush()


async def approve_hold(db: AsyncSession, hold_id: UUID, *, decided_by: UUID | None = None, source: str = "DRIVER_CHAT",
                       request: ApprovalRequest | None = None, now: datetime | None = None) -> Appointment:
    """Convert a hold into an appointment. Re-validates first. Past the last-start rule the appointment is
    PENDING_CONFIRMATION (planner must confirm) and the old appointment stays until then; otherwise it is CONFIRMED
    and the old appointment is replaced (marked not current, linked via replaced_appointment_id, slot released)."""
    now = now or _now()
    if source not in SOURCES:
        raise ValidationAppError("Unknown booking source")
    first = await db.get(SlotHold, hold_id)  # slot ids never change, so reading them needs no lock
    if first is None:
        raise NotFoundError("Hold not found")
    slot_ids = first.all_slot_ids
    await readers.lock_slots(db, slot_ids)  # lock order everywhere: slots -> shipment -> request -> hold -> appointment -> claims
    hold = (await db.execute(select(SlotHold).where(SlotHold.id == hold_id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if hold.status == "converted":
        found = await appointment_for_hold(db, hold.id)
        if found is not None:
            return found  # idempotent: approving twice gives the same appointment
    if hold.status == "released":
        raise ConflictError("HOLD_RELEASED", "This hold was released")
    if hold.status == "expired" or hold.expires_at <= now:
        if await readers.occupied_slot_ids(db, slot_ids, now, ignore_hold_ids=(hold.id,)):
            metrics.SLOT_TAKEN.inc()
            raise SlotTakenError(str(slot_ids[0]))
        other = await _active_hold(db, hold.shipment_id)
        if other is not None and other.id != hold.id:
            raise ConflictError("HOLD_EXPIRED", "This hold expired and the shipment now holds another slot")
        hold.status = "active"
        hold.expires_at = now + timedelta(minutes=5)
        await db.execute(update(SlotClaim).where(SlotClaim.hold_id == hold.id).values(active=True))
        await db.flush()
    ctx = await scheduling.load_context(db, hold.shipment_id)
    check = await scheduling.check_run(db, ctx, slot_ids, now, ignore_hold_ids=(hold.id,))
    if check.problems:
        metrics.INFEASIBLE_AT_REVALIDATION.inc()
        raise SlotUnavailableError(check.problems)
    current = await _current_active(db, hold.shipment_id)
    pending = check.needs_planner_approval
    if not pending and current is not None:
        await _replace(db, current, "REPLACED", now)
    appt = Appointment(
        code=await _next_code(db), shipment_id=hold.shipment_id, slot_id=slot_ids[0],
        appointment_status="PENDING_CONFIRMATION" if pending else "CONFIRMED", booking_source=source,
        is_current=not pending or current is None, booked_at=now, confirmed_at=None if pending else now,
        replaced_appointment_id=current.id if current is not None else None)
    db.add(appt)
    await db.flush()
    await db.execute(update(SlotClaim).where(SlotClaim.hold_id == hold.id, SlotClaim.active.is_(True))
                     .values(hold_id=None, appointment_id=appt.id))
    hold.status = "converted"
    if request is not None:
        request.status, request.decided_by, request.decided_at = "approved", decided_by, now
        metrics.APPROVAL_LATENCY.observe(max(0.0, (now - request.created_at).total_seconds()))
    metrics.HOLDS.labels("converted").inc()
    metrics.APPROVALS.labels("approved").inc()
    await db.flush()
    emit(db, "appointment.pending_confirmation" if pending else "appointment.confirmed",
         {"shipment_id": appt.shipment_id, "appointment_id": appt.id, "slot_id": appt.slot_id,
          "start": check.start.isoformat(), "end": check.end.isoformat(), "replaces": current.id if current else None})
    return appt


async def confirm_pending(db: AsyncSession, appointment_id: UUID, *, now: datetime | None = None) -> Appointment:
    now = now or _now()
    first = await db.get(Appointment, appointment_id)
    if first is None:
        raise NotFoundError("Appointment not found")
    slot_ids = await claimed_slot_ids(db, appointment_id) or [first.slot_id]  # legacy rows may have no claim yet
    await readers.lock_slots(db, slot_ids)  # slots before the appointment row (global lock order)
    appt = (await db.execute(select(Appointment).where(Appointment.id == appointment_id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if appt.appointment_status != "PENDING_CONFIRMATION":
        raise ConflictError("INVALID_STATE", f"Appointment is {appt.appointment_status}, not pending confirmation")
    ctx = await scheduling.load_context(db, appt.shipment_id)
    check = await scheduling.check_run(db, ctx, slot_ids, now, check_eta=False, ignore_appointment_ids=(appt.id,))
    if check.problems:
        metrics.INFEASIBLE_AT_REVALIDATION.inc()
        raise SlotUnavailableError(check.problems)
    old = await _current_active(db, appt.shipment_id)
    if old is not None and old.id != appt.id:
        await _replace(db, old, "REPLACED", now)
    appt.appointment_status, appt.confirmed_at, appt.is_current = "CONFIRMED", now, True
    metrics.APPROVALS.labels("confirmed").inc()
    emit(db, "appointment.confirmed", {"shipment_id": appt.shipment_id, "appointment_id": appt.id,
                                       "slot_id": appt.slot_id, "replaces": old.id if old else None})
    return appt


async def reject_pending(db: AsyncSession, appointment_id: UUID, reason: str) -> Appointment:
    appt = (await db.execute(select(Appointment).where(Appointment.id == appointment_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if appt is None:
        raise NotFoundError("Appointment not found")
    if appt.appointment_status != "PENDING_CONFIRMATION":
        raise ConflictError("INVALID_STATE", f"Appointment is {appt.appointment_status}, not pending confirmation")
    appt.appointment_status, appt.is_current, appt.cancellation_reason, appt.cancelled_at = "REJECTED", False, reason, _now()
    await _release_claims(db, appointment_id=appt.id)
    metrics.APPROVALS.labels("pending_rejected").inc()
    emit(db, "appointment.rejected", {"shipment_id": appt.shipment_id, "appointment_id": appt.id, "reason": reason})
    return appt


async def cancel_appointment(db: AsyncSession, appointment_id: UUID, reason: str, *, now: datetime | None = None) -> Appointment:
    appt = (await db.execute(select(Appointment).where(Appointment.id == appointment_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if appt is None:
        raise NotFoundError("Appointment not found")
    if appt.appointment_status == "IN_PROGRESS":
        raise ConflictError("FIXED_IN_PROGRESS", "A truck already unloading is fixed and cannot be cancelled here")
    if appt.appointment_status not in ("PENDING_CONFIRMATION", "CONFIRMED"):
        raise ConflictError("INVALID_STATE", f"A {appt.appointment_status} appointment cannot be cancelled")
    appt.appointment_status, appt.is_current, appt.cancelled_at, appt.cancellation_reason = "CANCELLED", False, now or _now(), reason
    await _release_claims(db, appointment_id=appt.id)
    emit(db, "appointment.cancelled", {"shipment_id": appt.shipment_id, "appointment_id": appt.id, "reason": reason})
    return appt


async def close_appointment(db: AsyncSession, appt: Appointment) -> None:
    """Free the capacity of an appointment that ended (completed / no-show / rejected)."""
    await _release_claims(db, appointment_id=appt.id)


# ---------------------------------------------------------------- approval requests (coordinator decisions)
async def create_request(db: AsyncSession, shipment_id: UUID, *, hold_id: UUID | None = None,
                         exception_id: UUID | None = None, reason_code: str | None = None) -> ApprovalRequest:
    hold = await db.get(SlotHold, hold_id) if hold_id else None
    r = ApprovalRequest(shipment_id=shipment_id, exception_id=exception_id, hold_id=hold_id,
                        slot_id=hold.slot_id if hold else None, status="waiting", reason_code=reason_code)
    db.add(r)
    await db.flush()
    emit(db, "request.created", {"shipment_id": shipment_id, "request_id": r.id, "reason_code": reason_code})
    return r


async def get_request(db: AsyncSession, request_id: UUID) -> ApprovalRequest:
    r = (await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if r is None:
        raise NotFoundError("Request not found")
    return r


def _open(r: ApprovalRequest) -> None:
    if r.status not in ("waiting", "held", "suggested"):
        raise ConflictError("REQUEST_CLOSED", f"This request is already {r.status}")


async def approve_request(db: AsyncSession, request_id: UUID, decided_by: UUID, now: datetime | None = None) -> Appointment:
    r = await get_request(db, request_id)
    _open(r)
    if r.hold_id is None:
        raise ConflictError("NO_HOLD", "This request has no held option to approve; suggest a slot first")
    return await approve_hold(db, r.hold_id, decided_by=decided_by, source="DRIVER_CHAT", request=r, now=now)


async def suggest(db: AsyncSession, request_id: UUID, slot_ids: list[UUID], decided_by: UUID, now: datetime | None = None) -> ApprovalRequest:
    """Coordinator offers another slot: it is held for the same driver and sent to them for acceptance."""
    r = await get_request(db, request_id)
    _open(r)
    hold = await place_hold(db, r.shipment_id, slot_ids, exception_id=r.exception_id, now=now)
    r.status, r.hold_id, r.suggested_slot_id, r.decided_by, r.decided_at = "suggested", hold.id, hold.slot_id, decided_by, now or _now()
    metrics.APPROVALS.labels("suggested").inc()
    emit(db, "request.suggested", {"shipment_id": r.shipment_id, "request_id": r.id, "hold_id": hold.id})
    return r


async def keep_hold(db: AsyncSession, request_id: UUID, decided_by: UUID, extend_minutes: int = 15,
                    decision_deadline: datetime | None = None, now: datetime | None = None) -> ApprovalRequest:
    now = now or _now()
    r = await get_request(db, request_id)
    _open(r)
    if r.hold_id is None:
        raise ConflictError("NO_HOLD", "There is no hold to keep")
    hold = (await db.execute(select(SlotHold).where(SlotHold.id == r.hold_id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if hold.status != "active":
        raise ConflictError("HOLD_NOT_ACTIVE", f"The hold is {hold.status}")
    limit = hold.created_at + timedelta(minutes=await _ttl(db, "max_hold_minutes", MAX_HOLD_MINUTES))
    new_expiry = min(max(hold.expires_at, now + timedelta(minutes=extend_minutes)), limit)
    hold.expires_at = new_expiry
    r.status, r.decided_by, r.decided_at, r.decision_deadline = "held", decided_by, now, decision_deadline or new_expiry
    emit(db, "request.held", {"shipment_id": r.shipment_id, "request_id": r.id, "expires_at": new_expiry.isoformat()})
    return r


async def reject_request(db: AsyncSession, request_id: UUID, decided_by: UUID, reason: str, now: datetime | None = None) -> ApprovalRequest:
    r = await get_request(db, request_id)
    _open(r)
    if r.hold_id is not None:
        await release_hold(db, r.hold_id, reason="request rejected")
    r.status, r.decided_by, r.decided_at, r.reason = "rejected", decided_by, now or _now(), reason
    metrics.APPROVALS.labels("rejected").inc()
    emit(db, "request.rejected", {"shipment_id": r.shipment_id, "request_id": r.id, "reason": reason})
    return r


async def create_replan_requests(db: AsyncSession, appointment_ids: list[UUID], reason_code: str) -> list[ApprovalRequest]:
    """A dock event or forced block invalidated these bookings: coordinators must re-plan them."""
    out = []
    for a in (await db.execute(select(Appointment).where(Appointment.id.in_(appointment_ids)))).scalars().all():
        dup = (await db.execute(select(ApprovalRequest.id).where(
            ApprovalRequest.shipment_id == a.shipment_id, ApprovalRequest.reason_code == reason_code,
            ApprovalRequest.status.in_(("waiting", "held", "suggested"))).limit(1))).first()
        if dup:
            continue
        r = ApprovalRequest(shipment_id=a.shipment_id, slot_id=a.slot_id, status="waiting", reason_code=reason_code)
        db.add(r)
        out.append(r)
        emit(db, "replan.requested", {"shipment_id": a.shipment_id, "appointment_id": a.id, "reason_code": reason_code})
    await db.flush()
    return out


# ---------------------------------------------------------------- move (planner drag-and-drop) and direct booking
async def validate_move(db: AsyncSession, appointment_id: UUID, slot_ids: list[UUID], now: datetime | None = None) -> scheduling.RunCheck:
    now = now or _now()
    appt = await db.get(Appointment, appointment_id)
    if appt is None:
        raise NotFoundError("Appointment not found")
    ctx = await scheduling.load_context(db, appt.shipment_id)
    return await scheduling.check_run(db, ctx, slot_ids, now, ignore_appointment_ids=(appt.id,))


async def move_appointment(db: AsyncSession, appointment_id: UUID, slot_ids: list[UUID], decided_by: UUID | None,
                           now: datetime | None = None) -> Appointment:
    await readers.lock_slots(db, list(dict.fromkeys(slot_ids)))  # target slots first (global lock order)
    appt = (await db.execute(select(Appointment).where(Appointment.id == appointment_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if appt is None:
        raise NotFoundError("Appointment not found")
    if appt.appointment_status == "IN_PROGRESS":
        raise ConflictError("FIXED_IN_PROGRESS", "A truck already unloading is fixed and never moved")
    if appt.appointment_status not in ("PENDING_CONFIRMATION", "CONFIRMED"):
        raise ConflictError("INVALID_STATE", f"A {appt.appointment_status} appointment cannot be moved")
    hold = await place_hold(db, appt.shipment_id, slot_ids, now=now)
    return await approve_hold(db, hold.id, decided_by=decided_by, source="PLANNER", now=now)


async def book(db: AsyncSession, shipment_id: UUID, slot_ids: list[UUID], decided_by: UUID | None, source: str = "PLANNER",
               now: datetime | None = None) -> Appointment:
    hold = await place_hold(db, shipment_id, slot_ids, now=now)
    return await approve_hold(db, hold.id, decided_by=decided_by, source=source, now=now)


# ---------------------------------------------------------------- escalation
async def escalate(db: AsyncSession, shipment_id: UUID | None, reason_code: str, handoff: dict, *,
                   exception_id: UUID | None = None) -> Escalation:
    e = Escalation(shipment_id=shipment_id, exception_id=exception_id, reason_code=reason_code, handoff_record=handoff)
    db.add(e)
    await db.flush()
    metrics.ESCALATIONS.labels(reason_code).inc()
    emit(db, "escalation.created", {"shipment_id": shipment_id, "escalation_id": e.id, "reason_code": reason_code})
    return e


async def options_or_escalate(db: AsyncSession, shipment_id: UUID, *, effective_eta=None, latest_finish=None, limit=5,
                              exception_id: UUID | None = None):
    """find_options; when nothing is feasible never invent an answer: open an escalation with a full hand-off."""
    res = await scheduling.find_options(db, shipment_id, effective_eta=effective_eta, latest_finish=latest_finish, limit=limit)
    if res.total_feasible > 0:
        return res, None
    ctx = await scheduling.load_context(db, shipment_id)
    s = ctx.shipment
    current = await _current_active(db, shipment_id)
    e = await escalate(db, shipment_id, "NO_FEASIBLE_SLOT", {
        "shipment": {"code": s.code, "priority": s.priority_code, "required_dock_type": s.required_dock_type,
                     "temperature_control_required": s.temperature_control_required, "load_weight_kg": s.load_weight_kg,
                     "expected_unload_min": s.expected_unload_min},
        "eta": {"ts": res.eta.ts.isoformat(), "source": res.eta.source, "confidence": res.eta.confidence,
                "requires_human_review": res.eta.requires_human_review} if res.eta else None,
        "latest_finish": latest_finish.isoformat() if latest_finish else None,
        "current_appointment": {"id": str(current.id), "status": current.appointment_status} if current else None,
        "rejections": res.rejections, "searched_hours": scheduling.DEFAULT_HORIZON_HOURS,
        "summary": "No compatible, free slot was found after the effective ETA within the search window."},
        exception_id=exception_id)
    return res, e


# ---------------------------------------------------------------- sweeper (arq cron, every minute)
async def sweep(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Expire holds and pending confirmations, mark no-shows (last 24 h only), flag stale ETAs. Idempotent."""
    from app.modules.booking import service as lifecycle

    now = now or _now()
    counts = {"holds_expired": 0, "pending_expired": 0, "no_shows": 0, "eta_stale": 0}
    due = [r[0] for r in (await db.execute(select(SlotHold.id).where(SlotHold.status == "active", SlotHold.expires_at <= now)
                                           .limit(500))).all()]
    if due:  # lock order: approval requests -> holds (the same order approve_request uses)
        await db.execute(select(ApprovalRequest.id).where(ApprovalRequest.hold_id.in_(due)).order_by(ApprovalRequest.id)
                         .with_for_update())
    holds = (await db.execute(select(SlotHold).where(SlotHold.id.in_(due), SlotHold.status == "active", SlotHold.expires_at <= now)
                              .with_for_update(skip_locked=True).execution_options(populate_existing=True))).scalars().all() if due else []
    for h in holds:
        await _close_hold(db, h, "expired")
        await db.execute(update(ApprovalRequest).where(ApprovalRequest.hold_id == h.id,
                                                       ApprovalRequest.status.in_(("waiting", "held", "suggested")))
                         .values(status="expired"))
        emit(db, "hold.expired", {"shipment_id": h.shipment_id, "hold_id": h.id})
        counts["holds_expired"] += 1
    ttl = await _ttl(db, "pending_confirmation_ttl_minutes", 30)
    pend = (await db.execute(select(Appointment).where(
        Appointment.appointment_status == "PENDING_CONFIRMATION", Appointment.booked_at <= now - timedelta(minutes=ttl))
        .with_for_update(skip_locked=True).execution_options(populate_existing=True).limit(500))).scalars().all()
    for a in pend:
        a.appointment_status, a.is_current, a.cancelled_at, a.cancellation_reason = "CANCELLED", False, now, "PENDING_EXPIRED"
        await _release_claims(db, appointment_id=a.id)
        emit(db, "pending.expired", {"shipment_id": a.shipment_id, "appointment_id": a.id})
        counts["pending_expired"] += 1
    counts["no_shows"] = await lifecycle.sweep_no_shows(db, now)
    counts["eta_stale"] = await lifecycle.sweep_stale_etas(db, now)
    await db.flush()
    for k, v in counts.items():
        if v:
            metrics.SWEEP.labels(k).inc(v)
    return counts
