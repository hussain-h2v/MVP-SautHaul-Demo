from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import Principal
from app.modules.coordinator import desk_handover_repository as repo
from app.modules.coordinator.desk_handover_schemas import (
    ActiveHold, HandoverDraft, HandoverIn, HandoverOut, OpenEscalation, OpenRequest, Snapshot,
)
from app.modules.coordinator.models import HandoverRecord

DEFAULT_SHIFT_HOURS = 8


async def snapshot(db: AsyncSession, since: datetime, now: datetime | None = None) -> Snapshot:
    now = now or datetime.now(UTC)
    return Snapshot(
        open_requests=[OpenRequest(id=r.id, shipment_code=code, status=r.status, priority_code=prio, reason_code=r.reason_code)
                       for r, code, prio in await repo.open_requests(db)],
        active_holds=[ActiveHold(id=h.id, shipment_code=code, expires_at=h.expires_at)
                      for h, code in await repo.active_holds(db, now)],
        open_escalations=[OpenEscalation(id=e.id, shipment_code=code, reason_code=e.reason_code, status=e.status)
                          for e, code in await repo.open_escalations(db)],
        pending_confirmations=await repo.pending_confirmations(db), failed_messages=await repo.failed_messages(db),
        decisions_made_since=await repo.decisions_since(db, since))


def brief(s: Snapshot, since: datetime) -> str:
    """Deterministic plain-text brief. An AI-written summary arrives in M7; this one is always available."""
    lines = [f"Shift handover since {since.astimezone(UTC):%Y-%m-%d %H:%M} UTC.",
             f"Decisions made this shift: {s.decisions_made_since}."]
    if s.open_requests:
        lines.append(f"Open requests ({len(s.open_requests)}): " + "; ".join(
            f"{r.shipment_code or 'no shipment'} {r.status} ({r.priority_code or 'n/a'})"
            + (f" [{r.reason_code}]" if r.reason_code else "") for r in s.open_requests[:10]) + ".")
    else:
        lines.append("No open requests.")
    if s.active_holds:
        lines.append(f"Active holds ({len(s.active_holds)}): " + "; ".join(
            f"{h.shipment_code} until {h.expires_at.astimezone(UTC):%H:%M} UTC" for h in s.active_holds[:10]) + ".")
    else:
        lines.append("No active holds.")
    if s.open_escalations:
        lines.append(f"Open escalations ({len(s.open_escalations)}): " + "; ".join(
            f"{e.shipment_code or 'no shipment'} {e.reason_code} ({e.status})" for e in s.open_escalations[:10]) + ".")
    else:
        lines.append("No open escalations.")
    lines.append(f"Bookings awaiting planner confirmation: {s.pending_confirmations}. "
                 f"Failed driver messages to check: {s.failed_messages}.")
    return "\n".join(lines)


async def draft(db: AsyncSession, since: datetime | None) -> HandoverDraft:
    now = datetime.now(UTC)
    since = since or now - timedelta(hours=DEFAULT_SHIFT_HOURS)
    snap = await snapshot(db, since, now)
    return HandoverDraft(shift_started_at=since, summary=brief(snap, since), snapshot=snap)


async def save(db: AsyncSession, p: Principal, body: HandoverIn) -> HandoverOut:
    snap = await snapshot(db, body.shift_started_at)  # recomputed here: never trust a client-supplied snapshot
    rec = HandoverRecord(author_id=p.user_id, shift_started_at=body.shift_started_at, summary=body.summary.strip(),
                         notes=body.notes, snapshot=snap.model_dump(mode="json"))
    db.add(rec)
    await db.flush()
    return _out(rec, p.full_name)


def _out(rec: HandoverRecord, author: str) -> HandoverOut:
    return HandoverOut(id=rec.id, author_id=rec.author_id, author_name=author, shift_started_at=rec.shift_started_at,
                       summary=rec.summary, notes=rec.notes, snapshot=rec.snapshot, created_at=rec.created_at)


async def list_records(db: AsyncSession, limit: int) -> list[HandoverOut]:
    return [_out(r, name) for r, name in await repo.list_records(db, limit)]
