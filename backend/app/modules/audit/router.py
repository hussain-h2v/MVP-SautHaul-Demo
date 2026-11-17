from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.listing import csv_response
from app.modules.audit.models import AuditLog
from app.modules.auth.deps import Principal, require

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    id: UUID
    actor_type: str
    actor_id: str | None
    action: str
    entity: str
    entity_id: str | None
    before: dict | None
    after: dict | None
    created_at: datetime


class AuditPage(BaseModel):
    total: int
    items: list[AuditOut]


@router.get("", response_model=AuditPage)
async def list_audit(
    entity: str | None = None, actor_id: str | None = None, action: str | None = None,
    limit: int = Query(50, le=200), offset: int = 0,
    p: Principal = Depends(require("audit_log", "R")), db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog)
    if p.role != "admin":  # coordinators see only their own actions
        stmt = stmt.where(AuditLog.actor_id == str(p.user_id))
    elif actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return AuditPage(total=total, items=[AuditOut.model_validate(r, from_attributes=True) for r in rows])


@router.get("/export.csv")
async def export_audit(
    entity: str | None = None, actor_id: str | None = None, action: str | None = None,
    p: Principal = Depends(require("audit_log", "R")), db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog)
    if p.role != "admin":
        stmt = stmt.where(AuditLog.actor_id == str(p.user_id))
    elif actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(10000))).scalars().all()
    fields = ["created_at", "actor_type", "actor_id", "action", "entity", "entity_id", "before", "after"]
    return csv_response("audit.csv", fields, [{f: getattr(r, f) for f in fields} for r in rows])
