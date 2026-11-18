from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.ai import monitoring, prompts, usage, usage_map
from app.modules.ai import router as ai_router
from app.modules.ai.admin_schemas import (
    BudgetIn, BudgetOut, BudgetPatch, PromptIn, PromptOut, PromptPatch, PromptTestIn, RollbackIn,
)
from app.modules.ai.config import invalidate_cache
from app.modules.ai.models import AIBudget, AIPrompt
from app.modules.ai.tasks import IntentExtraction
from app.modules.auth.deps import Principal, require

router = APIRouter(prefix="/ai", tags=["ai"])
read = require("ai_management", "R")
write = require("ai_management", "W")


def _p(p: AIPrompt) -> PromptOut:
    return PromptOut(id=p.id, task=p.task, language=p.language, prompt_version=p.prompt_version, template=p.template, status=p.status,
                     notes=p.notes, created_at=p.created_at)


# ---------------------------------------------------------------- prompts
@router.get("/prompts", response_model=list[PromptOut])
async def list_prompts(task: str | None = None, language: str | None = None, status: str | None = None,
                       _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    stmt = select(AIPrompt).order_by(AIPrompt.task, AIPrompt.language, AIPrompt.prompt_version.desc())
    for col, v in ((AIPrompt.task, task), (AIPrompt.language, language), (AIPrompt.status, status)):
        if v:
            stmt = stmt.where(col == v)
    return [_p(r) for r in (await db.execute(stmt)).scalars().all()]


@router.get("/prompts/diff")
async def prompt_diff(a: UUID, b: UUID, _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return prompts.diff((await prompts.get(db, a)).template, (await prompts.get(db, b)).template)


@router.post("/prompts/test")
async def prompt_test(body: PromptTestIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    """Playground: render the template (or a saved prompt) and run it once through the real router."""
    template = body.template if body.template else (await prompts.get(db, body.prompt_id)).template
    system = prompts.render(template, body.variables)
    ctx: dict = {"language": body.language}
    if body.model_id:
        ctx["force_model_id"] = body.model_id
    messages = [{"role": "system", "content": system}, {"role": "user", "content": f"<driver_message>\n{body.sample_message}\n</driver_message>"}]
    try:
        res = await ai_router.run(body.task, messages, response_schema=IntentExtraction if body.task == "intent_classify" else None, context=ctx)
    except ai_router.AIUnavailable as e:
        return {"unavailable": True, "reason": e.reason, "path": e.path, "rendered": system}
    parsed = res.parsed.model_dump() if hasattr(res.parsed, "model_dump") else res.parsed
    return {"unavailable": False, "rendered": system, "text": res.text, "parsed": parsed, "provider": res.provider, "model": res.model,
            "latency_ms": res.latency_ms, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "cost": str(res.cost),
            "fallback_depth": res.fallback_depth, "path": res.path}


@router.post("/prompts", response_model=PromptOut, status_code=201)
async def create_prompt(body: PromptIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row = await prompts.create_draft(db, body.task, body.language, body.template, body.notes, p.user_id)
    await db.commit()
    return _p(row)


@router.patch("/prompts/{prompt_id}", response_model=PromptOut)
async def update_prompt(prompt_id: UUID, body: PromptPatch, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row = await prompts.update_draft(db, prompt_id, body.template, body.notes)
    await db.commit()
    return _p(row)


@router.post("/prompts/{prompt_id}/activate", response_model=PromptOut)
async def activate_prompt(prompt_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row = await prompts.activate(db, prompt_id)
    await db.commit()
    return _p(row)


@router.post("/prompts/{prompt_id}/archive", response_model=PromptOut)
async def archive_prompt(prompt_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row = await prompts.archive(db, prompt_id)
    await db.commit()
    return _p(row)


@router.post("/prompts/{task}/{language}/rollback", response_model=PromptOut)
async def rollback_prompt(task: str, language: str, body: RollbackIn, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    row = await prompts.rollback(db, task, language, body.version, p.user_id)
    await db.commit()
    return _p(row)


# ---------------------------------------------------------------- usage
@router.get("/usage")
async def get_usage(date_from: datetime | None = None, date_to: datetime | None = None, group_by: str = "task",
                    _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await usage.usage(db, date_from, date_to, group_by)


# ---------------------------------------------------------------- budgets
@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(_: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    rows = list((await db.execute(select(AIBudget).order_by(AIBudget.scope, AIBudget.created_at))).scalars().all())
    return await usage.budget_out(db, rows)


@router.post("/budgets", response_model=BudgetOut, status_code=201)
async def create_budget(body: BudgetIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    b = await usage.create_budget(db, body)
    await db.commit()
    return (await usage.budget_out(db, [b]))[0]


@router.patch("/budgets/{budget_id}", response_model=BudgetOut)
async def update_budget(budget_id: UUID, body: BudgetPatch, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    b = await usage.update_budget(db, budget_id, body)
    await db.commit()
    return (await usage.budget_out(db, [b]))[0]


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(budget_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)) -> None:
    await usage.delete_budget(db, budget_id)
    await db.commit()


# ---------------------------------------------------------------- monitoring
@router.get("/monitoring")
async def get_monitoring(range: str = "7d", date_from: datetime | None = None, date_to: datetime | None = None, task: str | None = None,
                         provider: str | None = None, model: str | None = None, status: str | None = None,
                         _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await monitoring.overview(db, range_=range, date_from=date_from, date_to=date_to, task=task, provider=provider, model=model, status=status)


@router.get("/usage-map")
async def get_usage_map(_: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await usage_map.build(db)


# ---------------------------------------------------------------- logs
@router.get("/logs")
async def list_logs(request_id: str | None = None, trace_id: str | None = None, task: str | None = None, status: str | None = None,
                    provider: str | None = None, model: str | None = None, range: str | None = None, date_from: datetime | None = None,
                    date_to: datetime | None = None, fallback_only: bool = False, min_latency_ms: int | None = Query(None, ge=0),
                    min_cost: Decimal | None = Query(None, ge=0), sort: str = "created_at", direction: str = "desc",
                    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0), _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await monitoring.logs(db, range_=range, date_from=date_from, date_to=date_to, request_id=request_id, trace_id=trace_id, task=task,
                                 status=status, provider=provider, model=model, fallback_only=fallback_only, min_latency_ms=min_latency_ms,
                                 min_cost=min_cost, sort=sort, direction=direction, limit=limit, offset=offset)


@router.get("/logs/{log_id}")
async def get_log(log_id: UUID, _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await monitoring.trace(db, log_id)
