"""My activity: the caller's own decisions and actions with their outcomes, built from the audit log (read-only)
plus each entity's current status. Direct reads, noted in docs/DECISIONS.md."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointments.models import Appointment
from app.modules.audit.models import AuditLog
from app.modules.auth.deps import Principal
from app.modules.booking.models import ApprovalRequest, Escalation, SlotHold
from app.modules.coordinator.models import HandoverRecord
from app.modules.whatsapp.models import ChatMessage, ChatThread

ENTITIES = ("approval_requests", "appointments", "slot_holds", "escalations", "chat_threads", "chat_messages",
            "handover_records")
STATUS_COLUMNS = {
    "approval_requests": (ApprovalRequest, "status"), "appointments": (Appointment, "appointment_status"),
    "slot_holds": (SlotHold, "status"), "escalations": (Escalation, "status"), "chat_threads": (ChatThread, "thread_status"),
}


class ActivityRow(BaseModel):
    ts: datetime
    entity: str
    entity_id: str | None
    action: str
    summary: str
    outcome: str | None


def summarise(a: AuditLog) -> str:
    after, before = a.after or {}, a.before or {}
    e, act = a.entity, a.action
    if e == "approval_requests":
        if act == "insert":
            return "Created an approval request"
        if "status" in after:
            return f"Request {after['status']}" + (f": {after['reason']}" if after.get("reason") else "")
    if e == "appointments":
        if act == "insert":
            return f"Booked appointment {after.get('code', '')}".strip()
        if "appointment_status" in after:
            return f"Appointment {str(after['appointment_status']).lower().replace('_', ' ')}"
    if e == "slot_holds":
        if act == "insert":
            return "Placed a slot hold"
        if "status" in after:
            return f"Hold {after['status']}"
    if e == "escalations" and "status" in after:
        return f"Escalation {after['status'].replace('_', ' ')}"
    if e == "escalations" and "assigned_to" in after:
        return "Assigned an escalation"
    if e == "chat_threads" and "taken_over_by_user_id" in after:
        return "Took over a conversation" if after["taken_over_by_user_id"] else "Handed a conversation back to the bot"
    if e == "chat_messages" and act == "insert":
        return "Sent a reply to a driver"
    if e == "handover_records" and act == "insert":
        return "Saved a shift handover"
    return f"{act.capitalize()} {e.replace('_', ' ')}"


async def activity(db: AsyncSession, p: Principal, limit: int) -> list[ActivityRow]:
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.actor_type == "user", AuditLog.actor_id == str(p.user_id), AuditLog.entity.in_(ENTITIES))
        .order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
    outcomes: dict[tuple[str, str], str] = {}
    for entity, (model, col) in STATUS_COLUMNS.items():
        ids = [UUID(a.entity_id) for a in rows if a.entity == entity and a.entity_id]
        if ids:
            for i, st in (await db.execute(select(model.id, getattr(model, col)).where(model.id.in_(ids)))).all():
                outcomes[(entity, str(i))] = st
    fixed = {"chat_messages": "sent", "handover_records": "saved"}
    return [ActivityRow(ts=a.created_at, entity=a.entity, entity_id=a.entity_id, action=a.action, summary=summarise(a),
                        outcome=outcomes.get((a.entity, a.entity_id or "")) or fixed.get(a.entity)) for a in rows]
