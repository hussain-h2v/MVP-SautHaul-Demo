"""Read-only queries for the shift handover snapshot (approval requests, holds, escalations, pending confirmations,
failed messages). Direct reads, noted in docs/DECISIONS.md."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointments.models import Appointment
from app.modules.booking.models import ApprovalRequest, Escalation, SlotHold
from app.modules.coordinator.models import HandoverRecord
from app.modules.notifications.models import OperationalMessage
from app.modules.shipments.models import Shipment
from app.modules.users.models import User

PRIORITY = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}


async def open_requests(db: AsyncSession):
    rows = (await db.execute(
        select(ApprovalRequest, Shipment.code, Shipment.priority_code).join(Shipment, Shipment.id == ApprovalRequest.shipment_id)
        .where(ApprovalRequest.status.in_(("waiting", "held", "suggested"))).order_by(ApprovalRequest.created_at))).all()
    return sorted(rows, key=lambda r: PRIORITY.get(r[2], 2))


async def active_holds(db: AsyncSession, now: datetime):
    return (await db.execute(
        select(SlotHold, Shipment.code).join(Shipment, Shipment.id == SlotHold.shipment_id)
        .where(SlotHold.status == "active", SlotHold.expires_at > now).order_by(SlotHold.expires_at))).all()


async def open_escalations(db: AsyncSession):
    return (await db.execute(
        select(Escalation, Shipment.code).outerjoin(Shipment, Shipment.id == Escalation.shipment_id)
        .where(Escalation.status.in_(("open", "in_progress"))).order_by(Escalation.created_at))).all()


async def pending_confirmations(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(Appointment)
                             .where(Appointment.appointment_status == "PENDING_CONFIRMATION"))).scalar_one()


async def failed_messages(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(OperationalMessage)
                             .where(OperationalMessage.delivery_status == "FAILED"))).scalar_one()


async def decisions_since(db: AsyncSession, since: datetime) -> int:
    return (await db.execute(select(func.count()).select_from(ApprovalRequest)
                             .where(ApprovalRequest.decided_at.is_not(None), ApprovalRequest.decided_at >= since))).scalar_one()


async def list_records(db: AsyncSession, limit: int):
    return (await db.execute(select(HandoverRecord, User.full_name).join(User, User.id == HandoverRecord.author_id)
                             .order_by(HandoverRecord.created_at.desc()).limit(limit))).all()


async def user_name(db: AsyncSession, user_id) -> str:
    u = await db.get(User, user_id)
    return u.full_name if u else ""
