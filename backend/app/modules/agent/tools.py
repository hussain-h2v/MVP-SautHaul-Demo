"""The only things the agent may do, as typed tools. Identity (driver, thread, shipment) comes from the verified session
object, NEVER from model output or from the driver's text, so a message can never make the bot act for someone else.
Tools call the same services as the portals; the bot cannot create, change or release a slot except through
booking.engine (place_hold / release_hold) and cannot confirm anything."""
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointments import service as appointments_service
from app.modules.appointments.models import ACTIVE_STATUSES
from app.modules.booking import engine, readers
from app.modules.booking.models import ApprovalRequest, SlotHold
from app.modules.drivers import service as drivers_service
from app.modules.eta import service as eta_service
from app.modules.exceptions import service as exceptions_service
from app.modules.facilities import service as facilities_service
from app.modules.scheduling import service as scheduling
from app.modules.settings import service as settings_service
from app.modules.shipments import service as shipments_service
from app.modules.whatsapp.models import ChatMessage, ChatThread


@dataclass
class Session:
    """Verified identity for one conversation turn. Built by the channel, never by a model."""
    db: AsyncSession
    driver_id: UUID
    thread_id: UUID
    shipment_id: UUID | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


class AgentTools:
    def __init__(self, s: Session) -> None:
        self.s = s

    # ------------------------------------------------------------------ read tools
    async def get_driver_context(self) -> dict:
        d = (await drivers_service.get_many(self.s.db, [self.s.driver_id]))[self.s.driver_id]
        ships = await shipments_service.active_for_driver(self.s.db, d.id)
        fac = await facilities_service.summaries(self.s.db, list({x.destination_facility_id for x in ships}))
        return {"name": d.driver_name, "language": d.preferred_language, "carrier_id": d.carrier_id,
                "shipments": [{"id": x.id, "code": x.code, "facility_id": x.destination_facility_id,
                               "facility": fac.get(x.destination_facility_id, ("", ""))[1], "status": x.current_status,
                               "eta": x.latest_eta_ts or x.original_eta_ts} for x in ships]}

    async def _shipment(self):
        return (await shipments_service.get_many(self.s.db, [self.s.shipment_id]))[self.s.shipment_id]

    async def facility(self):
        s = await self._shipment()
        return (await readers.facilities_by_ids(self.s.db, [s.destination_facility_id]))[s.destination_facility_id]

    async def get_shipment_status(self) -> dict:
        db, sid = self.s.db, self.s.shipment_id
        s = await self._shipment()
        fac = await self.facility()
        eta = await eta_service.effective_eta(db, sid)
        appt = (await appointments_service.current_for_shipments(db, [sid])).get(sid)
        slot = None
        if appt is not None and appt.appointment_status in ACTIVE_STATUSES:
            sl = (await readers.slots_by_ids(db, [appt.slot_id]))[appt.slot_id]
            dock = (await readers.docks_by_ids(db, [sl.dock_id]))[sl.dock_id]
            slot = {"code": sl.code, "dock": dock.dock_code, "start": sl.slot_start_ts, "end": sl.slot_end_ts, "status": appt.appointment_status}
        req = await self.open_request()
        held = None
        if req is not None and req.hold_id:
            h = await self.s.db.get(SlotHold, req.hold_id)
            if h is not None and h.status == "active" and h.expires_at > self.s.now:
                sl = (await readers.slots_by_ids(db, h.all_slot_ids))
                first = sl[h.slot_id]
                dock = (await readers.docks_by_ids(db, [first.dock_id]))[first.dock_id]
                held = {"code": first.code, "dock": dock.dock_code, "start": first.slot_start_ts}
        return {"code": s.code, "status": s.current_status, "facility": fac.facility_name, "tz": fac.timezone,
                "eta": eta.ts if eta else None, "appointment": slot, "request_status": req.status if req else None, "held": held}

    async def open_request(self) -> ApprovalRequest | None:
        return (await self.s.db.execute(select(ApprovalRequest).where(
            ApprovalRequest.shipment_id == self.s.shipment_id, ApprovalRequest.status.in_(("waiting", "held", "suggested")))
            .order_by(ApprovalRequest.created_at.desc()).limit(1))).scalar_one_or_none()

    async def get_gate_info(self) -> dict:
        fac = await self.facility()
        contacts = await facilities_service.active_contacts(self.s.db, fac.id)
        gate = [c for c in contacts if "gate" in c.contact_role.lower()] or contacts
        return {"facility": fac.facility_name, "hours": f"{fac.open_time:%H:%M}-{fac.close_time:%H:%M}",
                "contact": f"{gate[0].contact_name} {gate[0].phone}".strip() if gate and gate[0].phone else None}

    async def coordinator_phone(self) -> str | None:
        v = await settings_service.get_value(self.s.db, "coordinator_phone", None)
        return v if isinstance(v, str) and v else None

    # ------------------------------------------------------------------ write tools (all through services)
    async def record_eta_update(self, eta: datetime, *, confidence: str, reason: str | None, note: str | None) -> None:
        await eta_service.record_update(self.s.db, self.s.shipment_id, source_type="DRIVER_DECLARED", declared_eta_ts=eta,
                                        confidence=confidence, reason=reason, note=(note or "")[:200] or None, driver_id=self.s.driver_id)

    async def record_arrival(self) -> None:
        await eta_service.record_update(self.s.db, self.s.shipment_id, source_type="DRIVER_DECLARED", declared_eta_ts=self.s.now,
                                        confidence="MEDIUM", reason=None, note="Driver reports arrival at the gate", driver_id=self.s.driver_id)
        engine.emit(self.s.db, "driver.arrived", {"shipment_id": self.s.shipment_id, "driver_id": self.s.driver_id})

    async def find_slot_options(self, eta: datetime | None, latest_finish: datetime | None, limit: int = 5):
        return await scheduling.find_options(self.s.db, self.s.shipment_id, effective_eta=eta, latest_finish=latest_finish,
                                             limit=limit, now=self.s.now)

    async def place_hold(self, slot_ids: list[UUID], exception_id: UUID | None):
        return await engine.place_hold(self.s.db, self.s.shipment_id, slot_ids, exception_id=exception_id, now=self.s.now)

    async def release_hold(self) -> None:
        h = (await self.s.db.execute(select(SlotHold).where(SlotHold.shipment_id == self.s.shipment_id, SlotHold.status == "active"))).scalar_one_or_none()
        if h is not None:
            await engine.release_hold(self.s.db, h.id, reason="driver released")

    async def create_escalation(self, reason_code: str, summary: str, extra: dict | None = None, exception_id: UUID | None = None):
        rows = (await self.s.db.execute(select(ChatMessage).where(ChatMessage.thread_id == self.s.thread_id)
                                        .order_by(ChatMessage.message_ts.desc()).limit(8))).scalars().all()
        transcript = [{"from": m.sender_type, "text": m.message_text[:300], "ts": m.message_ts.isoformat()} for m in reversed(rows)]
        eta = None
        handoff = {"summary": summary, "transcript": transcript, **(extra or {})}
        if self.s.shipment_id:
            s = await self._shipment()
            e = await eta_service.effective_eta(self.s.db, s.id)
            eta = {"ts": e.ts.isoformat(), "source": e.source, "confidence": e.confidence} if e else None
            handoff["shipment"] = {"code": s.code, "priority": s.priority_code, "status": s.current_status,
                                   "required_dock_type": s.required_dock_type, "expected_unload_min": s.expected_unload_min}
            handoff["eta"] = eta
        esc = await engine.escalate(self.s.db, self.s.shipment_id, reason_code, handoff, exception_id=exception_id)
        await self.set_thread(status="ESCALATED")
        if exception_id:
            await exceptions_service.set_status(self.s.db, exception_id, "ESCALATED")
        return esc

    # ------------------------------------------------------------------ internal helpers (not model-facing)
    async def set_thread(self, *, status: str | None = None, intent: str | None = None, shipment_id: UUID | None = None) -> None:
        t = await self.s.db.get(ChatThread, self.s.thread_id)
        if t is None:
            return
        if status:
            t.thread_status = status
        if intent:
            t.thread_intent = intent
        if shipment_id:
            t.shipment_id = shipment_id

    async def latest_request_status(self) -> str | None:
        return (await self.s.db.execute(select(ApprovalRequest.status).where(ApprovalRequest.shipment_id == self.s.shipment_id)
                                        .order_by(ApprovalRequest.created_at.desc()).limit(1))).scalar_one_or_none()

    async def latest_suggested_request(self) -> ApprovalRequest | None:
        return (await self.s.db.execute(select(ApprovalRequest).where(
            ApprovalRequest.shipment_id == self.s.shipment_id, ApprovalRequest.status == "suggested")
            .order_by(ApprovalRequest.created_at.desc()).limit(1))).scalar_one_or_none()


def to_local(dt: datetime | None, tz: str, with_date: bool = False) -> str:
    if dt is None:
        return "-"
    loc = dt.astimezone(ZoneInfo(tz))
    return loc.strftime("%d %b %H:%M") if with_date else loc.strftime("%H:%M")


def friendly(dt: datetime | None, tz: str, now: datetime) -> str:
    if dt is None:
        return "-"
    same_day = dt.astimezone(ZoneInfo(tz)).date() == now.astimezone(ZoneInfo(tz)).date()
    return to_local(dt, tz, with_date=not same_day)


_ = (re, timedelta)
