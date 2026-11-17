"""Coordinator inbox: one live list of everything that needs a human. Reads (never writes) across booking, exceptions,
notifications and ETA through the owning modules' services; the open request / hold / escalation queries are read-only
SQL on booking tables, owned by this desk (decision 50)."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking.models import ApprovalRequest, Escalation, SlotHold
from app.modules.coordinator import locks
from app.modules.coordinator.inbox_schemas import Counters, InboxItem, InboxOut
from app.modules.eta import service as eta_service
from app.modules.exceptions import service as exceptions_service
from app.modules.notifications import service as notifications_service
from app.modules.shipments import service as shipments_service

PRIORITY_RANK = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
SEVERITY_TO_PRIORITY = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "NORMAL", "LOW": "LOW"}  # exceptions without a shipment
EXPIRING_MIN = 5


async def _open_requests(db: AsyncSession):
    return list((await db.execute(select(ApprovalRequest).where(ApprovalRequest.status.in_(("waiting", "held", "suggested")))
                                  .order_by(ApprovalRequest.created_at).limit(300))).scalars().all())


async def _open_escalations(db: AsyncSession):
    return list((await db.execute(select(Escalation).where(Escalation.status.in_(("open", "in_progress")))
                                  .order_by(Escalation.created_at).limit(300))).scalars().all())


async def _expiring_holds(db: AsyncSession, now: datetime):
    return list((await db.execute(select(SlotHold).where(
        SlotHold.status == "active", SlotHold.expires_at > now, SlotHold.expires_at <= now + timedelta(minutes=EXPIRING_MIN))
        .order_by(SlotHold.expires_at))).scalars().all())


def _title(code: str | None, text: str) -> str:
    return f"{code}: {text}" if code else text


async def build(db: AsyncSession, redis: Redis, user_id: UUID, *, kind: str | None = None, facility_id: UUID | None = None,
                carrier_id: UUID | None = None, priority: str | None = None, status: str | None = None,
                claimed: str | None = None, limit: int = 200, now: datetime | None = None) -> InboxOut:
    from app.modules.carriers import service as carriers_service
    from app.modules.facilities import service as facilities_service

    now = now or datetime.now(UTC)
    raw: list[dict] = []
    reqs = await _open_requests(db)
    excs = await exceptions_service.list_open(db)
    escs = await _open_escalations(db)
    holds = await _expiring_holds(db, now)
    failed = await notifications_service.failed_operational_messages(db)
    etas = await eta_service.recent_changes(db)
    ship_ids = ({r.shipment_id for r in reqs} | {e.shipment_id for e in excs if e.shipment_id}
                | {e.shipment_id for e in escs if e.shipment_id} | {h.shipment_id for h in holds}
                | {m.shipment_id for m in failed} | {u.shipment_id for u in etas})
    ships = await shipments_service.get_many(db, list(ship_ids))
    carriers = await carriers_service.names(db, list({s.carrier_id for s in ships.values() if s.carrier_id}))
    facilities = await facilities_service.summaries(db, list({s.destination_facility_id for s in ships.values()}))

    def base(item_kind, item_id, shipment_id, status_, title, summary, created, expires=None, prio=None):
        s = ships.get(shipment_id) if shipment_id else None
        raw.append(dict(
            key=f"{item_kind}:{item_id}", kind=item_kind, id=item_id, shipment_id=shipment_id, shipment_code=s.code if s else None,
            carrier_name=carriers.get(s.carrier_id) if s and s.carrier_id else None,
            facility_code=facilities.get(s.destination_facility_id, ("", ""))[0] if s else None,
            facility_id=s.destination_facility_id if s else None, carrier_id=s.carrier_id if s else None,
            priority_code=prio or (s.priority_code if s else "NORMAL"), status=status_, title=title, summary=summary,
            created_at=created, expires_at=expires))

    for r in reqs:
        s = ships.get(r.shipment_id)
        what = "Re-plan needed" if (r.reason_code or "").startswith("REPLAN") else "Slot request"
        base("request", r.id, r.shipment_id, r.status, _title(s.code if s else None, what),
             f"{r.reason_code or 'Driver request'} - {r.status}", r.created_at)
    for e in excs:
        base("exception", e.id, e.shipment_id, e.exception_status, _title(ships[e.shipment_id].code if e.shipment_id in ships else None,
                                                                         f"Driver reported {e.exception_type.lower().replace('_', ' ')}"),
             (e.description or "")[:160], e.reported_at, prio=ships[e.shipment_id].priority_code if e.shipment_id in ships else SEVERITY_TO_PRIORITY.get(e.severity_code, "NORMAL"))
    for e in escs:
        base("escalation", e.id, e.shipment_id, e.status, _title(ships[e.shipment_id].code if e.shipment_id in ships else None,
                                                                f"Escalation: {e.reason_code.replace('_', ' ').lower()}"),
             (e.handoff_record or {}).get("summary", "Needs a human decision"), e.created_at)
    for h in holds:
        base("hold", h.id, h.shipment_id, "expiring", _title(ships[h.shipment_id].code if h.shipment_id in ships else None, "Hold about to expire"),
             f"Expires in {max(0, int((h.expires_at - now).total_seconds() // 60))} min", h.created_at, expires=h.expires_at)
    for m in failed:
        base("failed_message", m.id, m.shipment_id, "FAILED", _title(ships[m.shipment_id].code if m.shipment_id in ships else None,
                                                                    f"{m.channel.title()} message failed"),
             f"To {m.recipient_address}: {(m.subject or m.message_body)[:100]}", m.sent_at)
    for u in etas:
        base("eta_change", u.id, u.shipment_id, u.confidence_code, _title(ships[u.shipment_id].code if u.shipment_id in ships else None,
                                                                         f"ETA changed to {u.declared_eta_ts:%d %b %H:%M}"),
             f"{u.source_type.replace('_', ' ').title()}, {u.confidence_code.lower()} confidence"
             + (f", {u.delay_reason_code.lower()}" if u.delay_reason_code else ""), u.created_at)

    owners = await locks.owners(redis, [(i["kind"], str(i["id"])) for i in raw])
    counters = Counters()
    plural = {"request": "requests", "exception": "exceptions", "hold": "holds_expiring", "escalation": "escalations",
              "failed_message": "failed_messages", "eta_change": "eta_changes"}
    items: list[InboxItem] = []
    for i in raw:
        setattr(counters, plural[i["kind"]], getattr(counters, plural[i["kind"]]) + 1)
        owner = owners.get((i["kind"], str(i["id"])))
        if kind and i["kind"] != kind:
            continue
        if facility_id and i["facility_id"] != facility_id:
            continue
        if carrier_id and i["carrier_id"] != carrier_id:
            continue
        if priority and i["priority_code"] != priority:
            continue
        if status and i["status"] != status:
            continue
        if claimed == "mine" and not (owner and owner["id"] == str(user_id)):
            continue
        if claimed == "others" and not (owner and owner["id"] != str(user_id)):
            continue
        if claimed == "free" and owner:
            continue
        items.append(InboxItem(**{k: v for k, v in i.items() if k not in ("facility_id", "carrier_id")}, claimed_by=owner))
    counters.total = sum(getattr(counters, f) for f in plural.values())
    items.sort(key=lambda x: (PRIORITY_RANK.get(x.priority_code, 2), x.created_at))
    return InboxOut(counters=counters, items=items[:limit])
