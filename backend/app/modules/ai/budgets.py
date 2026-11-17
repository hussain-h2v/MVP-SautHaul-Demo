"""Budgets (global / provider / task / key, daily or monthly). A step whose budget is exhausted is skipped, so the
router falls back; alerts fire once per period when the threshold is crossed."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox import emit
from app.modules.ai.config import KeyCfg
from app.modules.ai.models import AIBudget, AIUsageLog


def period_start(period: str, now: datetime) -> datetime:
    now = now.astimezone(UTC)
    if period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def spend(db: AsyncSession, scope: str, scope_id: str | None, period: str, now: datetime) -> Decimal:
    stmt = select(func.coalesce(func.sum(AIUsageLog.cost), 0)).where(AIUsageLog.created_at >= period_start(period, now))
    if scope == "provider":
        stmt = stmt.where(AIUsageLog.provider == scope_id)
    elif scope == "task":
        stmt = stmt.where(AIUsageLog.task == scope_id)
    elif scope == "key":
        stmt = stmt.where(AIUsageLog.key_id == UUID(str(scope_id)))
    return Decimal((await db.execute(stmt)).scalar_one())


async def _applicable(db: AsyncSession, task: str, provider_id: UUID, provider_name: str, key_id: UUID | None) -> list[tuple[AIBudget, str | None]]:
    rows = (await db.execute(select(AIBudget).where(AIBudget.enabled.is_(True)))).scalars().all()
    out = []
    for b in rows:
        if b.scope == "global":
            out.append((b, None))
        elif b.scope == "provider" and b.scope_id in (str(provider_id), provider_name):
            out.append((b, provider_name))
        elif b.scope == "task" and b.scope_id == task:
            out.append((b, task))
        elif b.scope == "key" and key_id is not None and b.scope_id == str(key_id):
            out.append((b, str(key_id)))
    return out


async def exhausted(db: AsyncSession, *, task: str, provider_id: UUID, provider_name: str, key: KeyCfg | None,
                    now: datetime) -> str | None:
    """Name of the first exhausted budget, or None."""
    for b, sid in await _applicable(db, task, provider_id, provider_name, key.id if key else None):
        if await spend(db, b.scope, sid, b.period, now) >= b.limit_amount:
            return f"{b.scope}:{b.period}"
    if key is not None and key.monthly_budget is not None:
        if await spend(db, "key", str(key.id), "monthly", now) >= key.monthly_budget:
            return "key:monthly"
    return None


async def check_alerts(db: AsyncSession, redis: Redis, *, task: str, provider_id: UUID, provider_name: str,
                       key_id: UUID | None, now: datetime) -> None:
    for b, sid in await _applicable(db, task, provider_id, provider_name, key_id):
        used = await spend(db, b.scope, sid, b.period, now)
        if b.limit_amount > 0 and used >= b.limit_amount * Decimal(str(b.alert_threshold)):
            flag = f"ai:budget-alert:{b.id}:{period_start(b.period, now).date()}"
            if await redis.set(flag, "1", nx=True, ex=int(timedelta(days=40).total_seconds())):
                emit(db, "ai.budget_threshold", {
                    "title": f"AI budget {int(used / b.limit_amount * 100)}% used ({b.scope} {b.period})",
                    "body": f"Spent {used} of {b.limit_amount}", "budget_id": b.id, "scope": b.scope})
