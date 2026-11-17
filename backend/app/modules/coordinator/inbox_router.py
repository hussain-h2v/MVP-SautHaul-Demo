from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.events import publish_inbox_changed
from app.core.idempotency import get_redis
from app.core.errors import ValidationAppError
from app.modules.auth.deps import Principal, require
from app.modules.coordinator import competing_service, escalation_service, inbox_service, locks, request_service
from app.modules.coordinator.inbox_schemas import (
    AssignIn, ClaimIn, ClaimOut, DecideIn, DecideOut, EscalateIn, EscalationOut, InboxOut, ResolveIn, StatusIn,
)

router = APIRouter(prefix="/coordinator", tags=["coordinator"])
# Coordinator desk: escalations_takeover W is held by the coordinator role only (spec section 4).
desk = require("escalations_takeover", "W")


async def _redis():
    r = get_redis()
    try:
        yield r
    finally:
        await r.aclose()


@router.get("/inbox", response_model=InboxOut)
async def inbox(kind: str | None = None, facility_id: UUID | None = None, carrier_id: UUID | None = None,
                priority: str | None = None, status: str | None = None, claimed: str | None = None,
                limit: int = Query(200, ge=1, le=500), p: Principal = Depends(desk), db: AsyncSession = Depends(get_db),
                redis=Depends(_redis)):
    if kind and kind not in locks.KINDS:
        raise ValidationAppError("Unknown inbox kind", {"allowed": list(locks.KINDS)})
    return await inbox_service.build(db, redis, p.user_id, kind=kind, facility_id=facility_id, carrier_id=carrier_id,
                                     priority=priority, status=status, claimed=claimed, limit=limit)


@router.post("/claim", response_model=ClaimOut)
async def claim(body: ClaimIn, p: Principal = Depends(desk), redis=Depends(_redis)):
    if body.kind not in locks.KINDS:
        raise ValidationAppError("Unknown kind", {"allowed": list(locks.KINDS)})
    owner = await locks.claim(redis, body.kind, body.id, p.user_id, p.full_name)
    await publish_inbox_changed("claimed", kind=body.kind, id=str(body.id))
    return ClaimOut(claimed_by=owner, expires_at=datetime.now(UTC) + timedelta(seconds=locks.LOCK_TTL_SECONDS))


@router.post("/release", status_code=204)
async def release(body: ClaimIn, p: Principal = Depends(desk), redis=Depends(_redis)) -> None:
    await locks.release(redis, body.kind, body.id, p.user_id)
    await publish_inbox_changed("released", kind=body.kind, id=str(body.id))


@router.get("/requests/{request_id}")
async def request_detail(request_id: UUID, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db), redis=Depends(_redis)):
    return await request_service.detail(db, redis, request_id)


@router.post("/requests/{request_id}/escalate", response_model=EscalationOut, status_code=201)
async def escalate(request_id: UUID, body: EscalateIn, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db),
                   redis=Depends(_redis)):
    await locks.require_free(redis, "request", request_id, p.user_id)
    try:
        esc = await request_service.escalate(db, request_id, p.user_id, body.reason, body.note)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    await locks.release(redis, "request", request_id, p.user_id)
    await publish_inbox_changed("escalated", request_id=str(request_id))
    return await escalation_service.one(db, esc.id)


@router.get("/competing")
async def competing(facility_id: UUID | None = None, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db)):
    return {"groups": await competing_service.groups(db, facility_id)}


@router.post("/competing/decide", response_model=DecideOut)
async def competing_decide(body: DecideIn, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db), redis=Depends(_redis)):
    try:
        out = await competing_service.decide(db, redis, body, p.user_id)
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    await publish_inbox_changed("competing.decided")
    return out


@router.get("/escalations", response_model=list[EscalationOut])
async def escalations(status: str | None = None, limit: int = Query(100, ge=1, le=300), p: Principal = Depends(desk),
                      db: AsyncSession = Depends(get_db)):
    return await escalation_service.list_(db, status, limit)


@router.get("/escalations/{escalation_id}", response_model=EscalationOut)
async def escalation(escalation_id: UUID, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db)):
    return await escalation_service.one(db, escalation_id)


@router.post("/escalations/{escalation_id}/assign", response_model=EscalationOut)
async def assign(escalation_id: UUID, body: AssignIn, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db)):
    out = await escalation_service.assign(db, escalation_id, body.user_id or p.user_id)
    await db.commit()
    await publish_inbox_changed("escalation.assigned")
    return out


@router.post("/escalations/{escalation_id}/status", response_model=EscalationOut)
async def status(escalation_id: UUID, body: StatusIn, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db)):
    out = await escalation_service.set_status(db, escalation_id, body.status, p.user_id)
    await db.commit()
    await publish_inbox_changed("escalation.status")
    return out


@router.post("/escalations/{escalation_id}/resolve", response_model=EscalationOut)
async def resolve(escalation_id: UUID, body: ResolveIn, p: Principal = Depends(desk), db: AsyncSession = Depends(get_db)):
    out = await escalation_service.resolve(db, escalation_id, body.resolution, p.user_id)
    await db.commit()
    await publish_inbox_changed("escalation.resolved")
    return out
