"""Usage aggregates, budgets and the call log (read side of ai_usage_logs) plus log retention."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationAppError
from app.modules.ai import budgets as budget_calc
from app.modules.ai.admin_schemas import BudgetIn, BudgetOut, BudgetPatch
from app.modules.ai.models import TASKS, AIBudget, AIProvider, AIProviderKey, AIUsageLog

GROUPS = {
    "provider": "coalesce(provider, '(none)')",
    "model": "coalesce(model, '(none)')",
    "task": "task",
    "day": "to_char(date_trunc('day', created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD')",
}
_AGG = """count(*) AS requests, coalesce(sum(tokens_in), 0) AS tokens_in, coalesce(sum(tokens_out), 0) AS tokens_out,
  coalesce(sum(cost), 0) AS cost,
  coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0) AS p50_ms,
  coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) AS p95_ms,
  coalesce(avg((status <> 'ok')::int), 0) AS error_rate,
  coalesce(sum((status = 'ok' AND fallback_depth > 0)::int)::float / nullif(sum((status = 'ok')::int), 0), 0) AS fallback_rate"""


def _row(r) -> dict:
    return {"requests": int(r.requests), "tokens_in": int(r.tokens_in), "tokens_out": int(r.tokens_out), "cost": str(Decimal(r.cost)),
            "p50_ms": round(float(r.p50_ms)), "p95_ms": round(float(r.p95_ms)), "error_rate": round(float(r.error_rate), 4),
            "fallback_rate": round(float(r.fallback_rate), 4)}


async def usage(db: AsyncSession, date_from: datetime | None, date_to: datetime | None, group_by: str) -> dict:
    if group_by not in GROUPS:
        raise ValidationAppError("group_by must be one of " + ", ".join(GROUPS))
    now = datetime.now(UTC)
    params = {"f": date_from or now - timedelta(days=30), "t": date_to or now + timedelta(minutes=1)}
    where = "created_at >= :f AND created_at < :t"
    total = (await db.execute(text(f"SELECT {_AGG} FROM ai_usage_logs WHERE {where}"), params)).one()
    rows = (await db.execute(text(f"SELECT {GROUPS[group_by]} AS key, {_AGG} FROM ai_usage_logs WHERE {where} GROUP BY 1 ORDER BY 1"), params)).all()
    return {"group_by": group_by, "totals": _row(total), "rows": [{"key": r.key, **_row(r)} for r in rows]}


# ---------------------------------------------------------------- budgets
async def _label_and_spend(db: AsyncSession, b: AIBudget, now: datetime) -> tuple[str | None, Decimal]:
    if b.scope == "global":
        return "All AI", await budget_calc.spend(db, "global", None, b.period, now)
    if b.scope == "task":
        return b.scope_id, await budget_calc.spend(db, "task", b.scope_id, b.period, now)
    if b.scope == "provider":
        p = await db.get(AIProvider, UUID(b.scope_id)) if _is_uuid(b.scope_id) else None
        name = p.name if p else b.scope_id
        return name, await budget_calc.spend(db, "provider", name, b.period, now)
    k = await db.get(AIProviderKey, UUID(b.scope_id)) if _is_uuid(b.scope_id) else None
    return (k.label if k else b.scope_id), await budget_calc.spend(db, "key", b.scope_id, b.period, now)


def _is_uuid(v: str | None) -> bool:
    try:
        UUID(str(v))
        return True
    except ValueError:
        return False


async def budget_out(db: AsyncSession, rows: list[AIBudget]) -> list[BudgetOut]:
    now = datetime.now(UTC)
    out = []
    for b in rows:
        label, spent = await _label_and_spend(db, b, now)
        pct = float(spent / b.limit_amount * 100) if b.limit_amount else 0.0
        state = "exhausted" if spent >= b.limit_amount else "alert" if spent >= b.limit_amount * Decimal(str(b.alert_threshold)) else "ok"
        out.append(BudgetOut(id=b.id, scope=b.scope, scope_id=b.scope_id, scope_label=label, period=b.period, limit_amount=b.limit_amount,
                             alert_threshold=b.alert_threshold, enabled=b.enabled, spent=spent, percent=round(pct, 1), state=state))
    return out


async def _validate_scope(db: AsyncSession, scope: str, scope_id: str | None) -> None:
    if scope == "global":
        if scope_id:
            raise ValidationAppError("A global budget has no scope_id")
        return
    if not scope_id:
        raise ValidationAppError("scope_id is required for provider, task and key budgets")
    if scope == "task" and scope_id not in TASKS:
        raise ValidationAppError("Unknown task", {"allowed": list(TASKS)})
    if scope == "provider" and not (_is_uuid(scope_id) and await db.get(AIProvider, UUID(scope_id))):
        raise ValidationAppError("scope_id must be the id of an existing provider")
    if scope == "key" and not (_is_uuid(scope_id) and await db.get(AIProviderKey, UUID(scope_id))):
        raise ValidationAppError("scope_id must be the id of an existing key")


async def create_budget(db: AsyncSession, body: BudgetIn) -> AIBudget:
    await _validate_scope(db, body.scope, body.scope_id)
    b = AIBudget(**body.model_dump())
    db.add(b)
    await db.flush()
    return b


async def get_budget(db: AsyncSession, budget_id: UUID) -> AIBudget:
    b = await db.get(AIBudget, budget_id)
    if b is None:
        raise NotFoundError("Budget not found")
    return b


async def update_budget(db: AsyncSession, budget_id: UUID, body: BudgetPatch) -> AIBudget:
    b = await get_budget(db, budget_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    return b


async def delete_budget(db: AsyncSession, budget_id: UUID) -> None:
    await db.delete(await get_budget(db, budget_id))


# ---------------------------------------------------------------- logs
def _item(r: AIUsageLog, bodies: bool = False) -> dict:
    d = {"id": r.id, "request_id": r.request_id, "task": r.task, "provider": r.provider, "model": r.model, "key_id": r.key_id,
         "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "cost": str(r.cost), "latency_ms": r.latency_ms, "status": r.status,
         "fallback_depth": r.fallback_depth, "error_code": r.error_code, "trace_id": r.trace_id, "path": r.path, "created_at": r.created_at}
    if bodies:
        d.update(prompt_redacted=r.prompt_redacted, response_redacted=r.response_redacted)
    return d


async def logs(db: AsyncSession, *, request_id=None, task=None, status=None, provider=None, date_from=None, date_to=None, limit=50, offset=0) -> dict:
    stmt = select(AIUsageLog)
    for col, val in ((AIUsageLog.request_id, request_id), (AIUsageLog.task, task), (AIUsageLog.status, status), (AIUsageLog.provider, provider)):
        if val:
            stmt = stmt.where(col == val)
    if date_from:
        stmt = stmt.where(AIUsageLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AIUsageLog.created_at < date_to)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AIUsageLog.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return {"total": total, "items": [_item(r) for r in rows]}


async def log_detail(db: AsyncSession, log_id: UUID) -> dict:
    r = await db.get(AIUsageLog, log_id)
    if r is None:
        raise NotFoundError("Log entry not found")
    return _item(r, bodies=True)


async def delete_old_logs(db: AsyncSession, now: datetime | None = None) -> int:
    from app.modules.settings.models import SystemSetting

    now = now or datetime.now(UTC)
    row = (await db.execute(select(SystemSetting.value).where(SystemSetting.key == "ai_log_retention_days"))).first()
    days = int(row[0]) if row and row[0] is not None else 30
    res = await db.execute(delete(AIUsageLog).where(AIUsageLog.created_at < now - timedelta(days=days)))
    return res.rowcount or 0
