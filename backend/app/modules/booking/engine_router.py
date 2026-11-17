from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.guards import facility_staff
from app.modules.appointments.models import Appointment
from app.modules.auth.deps import Principal, require_any
from app.modules.booking import engine
from app.modules.booking.engine_schemas import (
    BookedOut, BookIn, CancelIn, HoldIn, HoldOut, KeepHoldIn, MoveCheckOut, MoveIn, RejectRequestIn, RequestIn,
    RequestOut, SuggestIn,
)
from app.modules.booking.models import ApprovalRequest, SlotHold
from app.modules.booking.service import publish_change
from app.modules.scheduling import service as scheduling_service
from app.modules.scheduling.router import to_out
from app.modules.scheduling.schemas import OptionsIn, OptionsOut
from app.modules.shipments import service as shipments_service
from app.modules.shipments.models import Shipment

router = APIRouter(prefix="/booking", tags=["booking"])
read = facility_staff("booking_decisions", "R")
decide = facility_staff("booking_decisions", "W")


def _mover():
    base = require_any(("day_schedule", "W"), ("booking_decisions", "W"))

    async def dep(p: Principal = Depends(base)) -> Principal:
        if p.role == "carrier_user":
            from app.core.errors import ForbiddenError

            raise ForbiddenError("Facility operations are not available to carrier users")
        return p

    return dep


mover = _mover()


async def _shipment(db: AsyncSession, p: Principal, shipment_id: UUID) -> Shipment:
    return await shipments_service.get_scoped(db, p, shipment_id)


def _hold_out(h: SlotHold, code: str | None = None) -> HoldOut:
    left = max(0, int((h.expires_at - datetime.now(UTC)).total_seconds()))
    return HoldOut(id=h.id, shipment_id=h.shipment_id, shipment_code=code, slot_ids=h.all_slot_ids, status=h.status,
                   expires_at=h.expires_at, seconds_left=left if h.status == "active" else 0)


def _req_out(r: ApprovalRequest, code: str | None = None) -> RequestOut:
    return RequestOut(id=r.id, shipment_id=r.shipment_id, shipment_code=code, status=r.status, reason_code=r.reason_code,
                      hold_id=r.hold_id, slot_id=r.slot_id, suggested_slot_id=r.suggested_slot_id, reason=r.reason,
                      decision_deadline=r.decision_deadline, created_at=r.created_at)


def _booked(a: Appointment, pending: bool) -> BookedOut:
    return BookedOut(appointment_id=a.id, code=a.code, appointment_status=a.appointment_status, is_current=a.is_current,
                     slot_id=a.slot_id, replaced_appointment_id=a.replaced_appointment_id, needs_planner_approval=pending)


async def _notify(db: AsyncSession, shipment_id: UUID, reason: str) -> None:
    s = (await shipments_service.get_many(db, [shipment_id])).get(shipment_id)
    if s is not None:
        await publish_change(s.destination_facility_id, reason, shipment_id=str(shipment_id))


# ---------------------------------------------------------------- options (never reserves)
@router.post("/options", response_model=OptionsOut)
async def options(body: OptionsIn, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    """Ranked feasible options. With escalate_if_none an empty result opens an escalation with a hand-off record."""
    await _shipment(db, p, body.shipment_id)
    res, esc = await engine.options_or_escalate(
        db, body.shipment_id, effective_eta=body.effective_eta, latest_finish=body.latest_finish, limit=body.limit) \
        if body.escalate_if_none else (await scheduling_service.find_options(
            db, body.shipment_id, effective_eta=body.effective_eta, latest_finish=body.latest_finish, limit=body.limit), None)
    if esc is not None:
        await db.commit()
    return to_out(body.shipment_id, res, esc.id if esc else None,
                  "No feasible slot: escalated to a coordinator with a full hand-off record." if esc else None)


# ---------------------------------------------------------------- holds
@router.post("/holds", response_model=HoldOut, status_code=201)
async def place_hold(body: HoldIn, p: Principal = Depends(decide), db: AsyncSession = Depends(get_db)):
    s = await _shipment(db, p, body.shipment_id)
    try:
        hold = await engine.place_hold(db, body.shipment_id, body.slot_ids, exception_id=body.exception_id)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    await _notify(db, body.shipment_id, "hold.placed")
    return _hold_out(hold, s.code)


@router.get("/holds", response_model=list[HoldOut])
async def list_holds(p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    now = datetime.now(UTC)
    rows = (await db.execute(select(SlotHold, Shipment).join(Shipment, Shipment.id == SlotHold.shipment_id)
                             .where(SlotHold.status == "active", SlotHold.expires_at > now)
                             .order_by(SlotHold.expires_at))).all()
    out = []
    for h, s in rows:
        if await shipments_service.visible_to(db, p, s.id):
            out.append(_hold_out(h, s.code))
    return out


@router.post("/holds/{hold_id}/release", response_model=HoldOut)
async def release(hold_id: UUID, p: Principal = Depends(decide), db: AsyncSession = Depends(get_db)):
    h = await db.get(SlotHold, hold_id)
    if h is None:
        raise NotFoundError("Hold not found")
    s = await _shipment(db, p, h.shipment_id)
    h = await engine.release_hold(db, hold_id, reason="released by coordinator")
    await db.commit()
    await _notify(db, h.shipment_id, "hold.released")
    return _hold_out(h, s.code)


# ---------------------------------------------------------------- coordinator decisions
async def _scoped_request(db: AsyncSession, p: Principal, request_id: UUID) -> ApprovalRequest:
    r = await db.get(ApprovalRequest, request_id)
    if r is None:
        raise NotFoundError("Request not found")
    await _shipment(db, p, r.shipment_id)
    return r


@router.post("/requests", response_model=RequestOut, status_code=201)
async def create_request(body: RequestIn, p: Principal = Depends(decide), db: AsyncSession = Depends(get_db)):
    s = await _shipment(db, p, body.shipment_id)
    r = await engine.create_request(db, body.shipment_id, hold_id=body.hold_id, exception_id=body.exception_id,
                                    reason_code=body.reason_code)
    await db.commit()
    return _req_out(r, s.code)


@router.get("/requests", response_model=list[RequestOut])
async def list_requests(status: str | None = None, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    stmt = select(ApprovalRequest, Shipment).join(Shipment, Shipment.id == ApprovalRequest.shipment_id)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    out = []
    for r, s in (await db.execute(stmt.order_by(ApprovalRequest.created_at.desc()).limit(500))).all():
        if await shipments_service.visible_to(db, p, s.id):
            out.append(_req_out(r, s.code))
    return out


@router.post("/requests/{request_id}/approve", response_model=BookedOut)
async def approve(request_id: UUID, p: Principal = Depends(decide), db: AsyncSession = Depends(get_db)):
    r = await _scoped_request(db, p, request_id)
    try:
        appt = await engine.approve_request(db, request_id, p.user_id)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    await _notify(db, r.shipment_id, "request.approved")
    return _booked(appt, appt.appointment_status == "PENDING_CONFIRMATION")


@router.post("/requests/{request_id}/suggest", response_model=RequestOut)
async def suggest(request_id: UUID, body: SuggestIn, p: Principal = Depends(decide), db: AsyncSession = Depends(get_db)):
    await _scoped_request(db, p, request_id)
    try:
        r = await engine.suggest(db, request_id, body.slot_ids, p.user_id)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    await _notify(db, r.shipment_id, "request.suggested")
    return _req_out(r)


@router.post("/requests/{request_id}/hold", response_model=RequestOut)
async def keep_hold(request_id: UUID, body: KeepHoldIn, p: Principal = Depends(decide), db: AsyncSession = Depends(get_db)):
    await _scoped_request(db, p, request_id)
    r = await engine.keep_hold(db, request_id, p.user_id, body.extend_minutes, body.decision_deadline)
    await db.commit()
    return _req_out(r)


@router.post("/requests/{request_id}/reject", response_model=RequestOut)
async def reject(request_id: UUID, body: RejectRequestIn, p: Principal = Depends(decide), db: AsyncSession = Depends(get_db)):
    await _scoped_request(db, p, request_id)
    r = await engine.reject_request(db, request_id, p.user_id, body.reason)
    await db.commit()
    await _notify(db, r.shipment_id, "request.rejected")
    return _req_out(r)


# ---------------------------------------------------------------- direct booking, move, cancel
@router.post("/book", response_model=BookedOut, status_code=201)
async def book(body: BookIn, p: Principal = Depends(mover), db: AsyncSession = Depends(get_db)):
    await _shipment(db, p, body.shipment_id)
    try:
        appt = await engine.book(db, body.shipment_id, body.slot_ids, p.user_id, source="PLANNER")
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    await _notify(db, body.shipment_id, "appointment.booked")
    return _booked(appt, appt.appointment_status == "PENDING_CONFIRMATION")


async def _scoped_appt(db: AsyncSession, p: Principal, appointment_id: UUID) -> Appointment:
    a = await db.get(Appointment, appointment_id)
    if a is None:
        raise NotFoundError("Appointment not found")
    await _shipment(db, p, a.shipment_id)
    return a


@router.post("/appointments/{appointment_id}/validate-move", response_model=MoveCheckOut)
async def validate_move(appointment_id: UUID, body: MoveIn, p: Principal = Depends(mover), db: AsyncSession = Depends(get_db)):
    """Dry run for drag-and-drop: is the target feasible, and would it need planner approval?"""
    await _scoped_appt(db, p, appointment_id)
    c = await engine.validate_move(db, appointment_id, body.slot_ids)
    return MoveCheckOut(feasible=not c.problems, problems=c.problems, needs_planner_approval=c.needs_planner_approval)


@router.post("/appointments/{appointment_id}/move", response_model=BookedOut)
async def move(appointment_id: UUID, body: MoveIn, p: Principal = Depends(mover), db: AsyncSession = Depends(get_db)):
    a = await _scoped_appt(db, p, appointment_id)
    try:
        new = await engine.move_appointment(db, appointment_id, body.slot_ids, p.user_id)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    await _notify(db, a.shipment_id, "appointment.moved")
    return _booked(new, new.appointment_status == "PENDING_CONFIRMATION")


@router.post("/appointments/{appointment_id}/cancel", response_model=BookedOut)
async def cancel(appointment_id: UUID, body: CancelIn, p: Principal = Depends(mover), db: AsyncSession = Depends(get_db)):
    a = await _scoped_appt(db, p, appointment_id)
    a = await engine.cancel_appointment(db, appointment_id, body.reason)
    await db.commit()
    await _notify(db, a.shipment_id, "appointment.cancelled")
    return _booked(a, False)
