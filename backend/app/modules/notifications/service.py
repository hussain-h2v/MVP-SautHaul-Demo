"""In-app notifications and the outbox worker step.

State changes write outbox_events in their own transaction; `process_outbox` (worker job) turns each event into
notifications for the right audiences and marks it sent. Failures back off and are retried (max 5 attempts)."""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.errors import NotFoundError
from app.modules.appointments import service as appointments_service
from app.modules.auth.deps import Principal
from app.modules.notifications import repository
from app.modules.notifications.models import Notification, OutboxEvent
from app.modules.notifications.schemas import NotificationOut, NotificationPage
from app.modules.shipments import service as shipments_service
from app.modules.slots import service as slots_service

MAX_ATTEMPTS = 5
TZ = ZoneInfo("Asia/Kolkata")
CARRIER_EVENTS = {
    "shipment.offered", "appointment.confirmed", "appointment.pending_confirmation", "appointment.rejected",
    "appointment.cancelled", "appointment.no_show", "request.suggested", "request.held", "request.rejected",
    "hold.placed", "hold.expired", "pending.expired", "escalation.created", "replan.requested", "eta.stale",
}


@dataclass
class Audience:
    role: str
    carrier_id: UUID | None = None
    facility_id: UUID | None = None


@dataclass
class ProcessResult:
    sent: int = 0
    failed: int = 0
    notifications: int = 0
    to_publish: list[tuple[UUID | None, UUID | None, dict]] = field(default_factory=list)


def _fmt(dt: datetime | None) -> str:
    return dt.astimezone(TZ).strftime("%d %b %H:%M") if dt else ""


async def _slot_text(db: AsyncSession, payload: dict) -> str:
    slot_id = payload.get("slot_id")
    if not slot_id and payload.get("appointment_id"):
        a = await appointments_service.get(db, UUID(str(payload["appointment_id"])))
        slot_id = a.slot_id if a else None
    if not slot_id:
        return ""
    w = (await slots_service.windows(db, [UUID(str(slot_id))])).get(UUID(str(slot_id)))
    return f"{w[0]}, {_fmt(w[1])}-{_fmt(w[2])[-5:]}" if w else ""


TITLES = {
    "shipment.offered": "New shipment offered: {code}",
    "appointment.confirmed": "Slot confirmed for {code}: {slot}",
    "appointment.pending_confirmation": "Slot awaiting planner confirmation for {code}: {slot}",
    "appointment.rejected": "Slot rejected for {code}: {slot}",
    "appointment.cancelled": "Appointment cancelled for {code}: {slot}",
    "appointment.no_show": "Marked no-show: {code}",
    "request.suggested": "Another slot suggested for {code}",
    "request.held": "Slot kept on hold for {code}",
    "request.rejected": "Slot request rejected for {code}",
    "hold.placed": "Slot held for {code}",
    "hold.expired": "Slot hold expired for {code}",
    "pending.expired": "Pending confirmation expired for {code}",
    "escalation.created": "Escalated to a coordinator: {code}",
    "replan.requested": "Booking needs re-planning for {code}",
    "eta.stale": "ETA is out of date for {code}",
    "shipment.reassigned": "Driver or vehicle reassigned for {code}",
    "shipment.offer_responded": "Carrier responded to the offer for {code}",
    "shipment.assigned": "Driver and vehicle assigned to {code}",
}


def audiences(event_type: str, carrier_id: UUID | None, facility_id: UUID | None) -> list[Audience]:
    out: list[Audience] = []
    if event_type in CARRIER_EVENTS and carrier_id:
        out.append(Audience("carrier_user", carrier_id=carrier_id))
    if event_type in ("appointment.pending_confirmation", "replan.requested"):
        out.append(Audience("facility_planner", facility_id=facility_id))
    if event_type in ("escalation.created", "shipment.reassigned", "eta.stale", "shipment.offer_responded", "shipment.assigned"):
        out.append(Audience("coordinator"))
    return out


async def notify(db: AsyncSession, *, type: str, title: str, body: str = "", payload: dict | None = None,
                 role: str | None = None, user_id: UUID | None = None, carrier_id: UUID | None = None,
                 facility_id: UUID | None = None) -> Notification:
    n = Notification(recipient_user_id=user_id, recipient_role=role, carrier_id=carrier_id, facility_id=facility_id,
                     type=type, title=title[:300], body=body, payload=payload or {})
    db.add(n)
    await db.flush()
    return n


async def _project(db: AsyncSession, ev: OutboxEvent, res: ProcessResult) -> None:
    payload = ev.payload or {}
    if ev.event_type not in TITLES or not payload.get("shipment_id"):
        return  # unknown type: nothing to show, still marked sent
    sid = UUID(str(payload["shipment_id"]))
    ship = (await shipments_service.get_many(db, [sid])).get(sid)
    if ship is None:
        return
    auds = audiences(ev.event_type, ship.carrier_id, ship.destination_facility_id)
    if not auds:
        return
    slot = await _slot_text(db, payload)
    title = TITLES[ev.event_type].format(code=ship.code, slot=slot).replace(": :", ":").rstrip(": ")
    body = payload.get("reason") or payload.get("reason_code") or ""
    for a in auds:
        await notify(db, type=ev.event_type, title=title, body=str(body),
                     payload={**payload, "shipment_code": ship.code}, role=a.role, carrier_id=a.carrier_id,
                     facility_id=a.facility_id)
        res.notifications += 1
        res.to_publish.append((a.facility_id or ship.destination_facility_id, a.carrier_id,
                               {"type": ev.event_type, "title": title, "shipment_id": str(sid)}))


async def process_outbox(db: AsyncSession, limit: int = 200, now: datetime | None = None) -> ProcessResult:
    """Drain pending (and due, retryable failed) outbox rows. Idempotent: each event is projected exactly once because
    it is locked, projected and marked sent in one transaction."""
    now = now or datetime.now(UTC)
    rows = (await db.execute(
        select(OutboxEvent).where(
            or_(OutboxEvent.status == "pending",
                (OutboxEvent.status == "failed") & (OutboxEvent.attempts < MAX_ATTEMPTS)),
            or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now))
        .order_by(OutboxEvent.created_at).limit(limit).with_for_update(skip_locked=True).execution_options(populate_existing=True)
    )).scalars().all()
    res = ProcessResult()
    for ev in rows:
        try:
            async with db.begin_nested():
                await _project(db, ev, res)
            ev.status, ev.attempts, ev.next_attempt_at = "sent", ev.attempts + 1, None
            res.sent += 1
        except Exception:
            ev.status, ev.attempts = "failed", ev.attempts + 1
            ev.next_attempt_at = now + timedelta(minutes=min(2 ** ev.attempts, 60))
            res.failed += 1
    await db.flush()
    return res


async def run_outbox(db: AsyncSession, limit: int = 200) -> ProcessResult:
    """Worker entry: project, commit, then publish live events (best effort, after the commit)."""
    res = await process_outbox(db, limit)
    await db.commit()
    for facility_id, carrier_id, payload in res.to_publish:
        try:
            await events.publish("notification.created", payload, facility_id=facility_id, carrier_id=carrier_id)
        except Exception:
            pass
    return res


async def list_for(db: AsyncSession, p: Principal, unread_only: bool, limit: int, offset: int) -> NotificationPage:
    total, unread, rows, read_ids = await repository.list_page(db, p, unread_only, limit, offset)
    return NotificationPage(total=total, unread=unread, items=[
        NotificationOut(id=n.id, type=n.type, title=n.title, body=n.body, payload=n.payload, created_at=n.created_at,
                        read=n.id in read_ids) for n in rows])


async def mark_read(db: AsyncSession, p: Principal, notification_id: UUID) -> None:
    if await repository.get_visible(db, p, notification_id) is None:
        raise NotFoundError("Notification not found")
    await repository.mark_read(db, p, notification_id)


async def read_all(db: AsyncSession, p: Principal) -> int:
    return await repository.mark_all_read(db, p)
