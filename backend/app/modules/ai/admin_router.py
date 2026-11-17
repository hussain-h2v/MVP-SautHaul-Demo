from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.idempotency import get_redis
from app.modules.ai import admin_service as svc
from app.modules.ai import router as ai_router
from app.modules.ai.admin_schemas import (
    EnabledIn, FailureIn, KeyIn, KeyOut, KeyPatch, ModelIn, ModelOut, ModelPatch, ModelTestIn, ModelTestOut, PlaygroundIn, ProviderIn,
    ProviderOut, ProviderPatch, RotateIn, RouteOut, RoutePut, RouteSimOut, SafetyPut, TestOut,
)
from app.modules.ai.config import invalidate_cache
from app.modules.ai.models import AIModel, AIProvider, AIProviderKey
from app.modules.ai.tasks import IntentExtraction
from app.modules.auth.deps import Principal, require

router = APIRouter(prefix="/ai", tags=["ai"])
read = require("ai_management", "R")
write = require("ai_management", "W")


async def _redis():
    r = get_redis()
    try:
        yield r
    finally:
        await r.aclose()


# ---------------------------------------------------------------- providers
@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(_: Principal = Depends(read), db: AsyncSession = Depends(get_db), redis=Depends(_redis)):
    rows = list((await db.execute(select(AIProvider).order_by(AIProvider.name))).scalars().all())
    return await svc.provider_out(db, redis, rows)


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(body: ProviderIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db), redis=Depends(_redis)):
    p = await svc.create_provider(db, body)
    await db.commit()
    return (await svc.provider_out(db, redis, [p]))[0]


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(provider_id: UUID, body: ProviderPatch, _: Principal = Depends(write), db: AsyncSession = Depends(get_db),
                          redis=Depends(_redis)):
    p = await svc.update_provider(db, provider_id, body)
    await db.commit()
    invalidate_cache()
    return (await svc.provider_out(db, redis, [p]))[0]


@router.delete("/providers/{provider_id}", response_model=ProviderOut)
async def disable_provider(provider_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db), redis=Depends(_redis)):
    p = await svc.disable_provider(db, provider_id)
    await db.commit()
    invalidate_cache()
    return (await svc.provider_out(db, redis, [p]))[0]


@router.post("/providers/{provider_id}/test", response_model=TestOut)
async def test_provider(provider_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    ok, ms, model, err = await svc.test_provider(db, provider_id)
    await db.commit()
    return TestOut(ok=ok, latency_ms=ms, model=model, error=err)


@router.post("/providers/{provider_id}/simulate-failure", status_code=204)
async def simulate_provider_failure(provider_id: UUID, body: FailureIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db),
                                    redis=Depends(_redis)) -> None:
    await svc.get_provider(db, provider_id)
    await svc.set_fault(redis, provider_id, body.error_code, body.seconds)


@router.delete("/providers/{provider_id}/simulate-failure", status_code=204)
async def clear_provider_failure(provider_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db), redis=Depends(_redis)) -> None:
    await svc.get_provider(db, provider_id)
    await svc.clear_fault(redis, provider_id)


class LoadedModels(BaseModel):
    added: list[str]


@router.post("/providers/{provider_id}/load-models", response_model=LoadedModels)
async def load_models(provider_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    added = await svc.load_models(db, provider_id)
    await db.commit()
    invalidate_cache()
    return LoadedModels(added=added)


# ---------------------------------------------------------------- keys (never returned: only the last four characters)
@router.get("/keys", response_model=list[KeyOut])
async def list_keys(provider_id: UUID | None = None, _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    stmt = select(AIProviderKey).order_by(AIProviderKey.created_at)
    if provider_id:
        stmt = stmt.where(AIProviderKey.provider_id == provider_id)
    return await svc.key_out(db, list((await db.execute(stmt)).scalars().all()))


@router.post("/keys", response_model=KeyOut, status_code=201)
async def create_key(body: KeyIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    k = await svc.create_key(db, body)
    await db.commit()
    invalidate_cache()
    return (await svc.key_out(db, [k]))[0]


@router.patch("/keys/{key_id}", response_model=KeyOut)
async def update_key(key_id: UUID, body: KeyPatch, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    k = await svc.update_key(db, key_id, body)
    await db.commit()
    invalidate_cache()
    return (await svc.key_out(db, [k]))[0]


@router.post("/keys/{key_id}/rotate", response_model=KeyOut)
async def rotate_key(key_id: UUID, body: RotateIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    k = await svc.rotate_key(db, key_id, body.api_key)
    await db.commit()
    invalidate_cache()
    return (await svc.key_out(db, [k]))[0]


@router.delete("/keys/{key_id}", response_model=KeyOut)
async def disable_key(key_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    k = await svc.update_key(db, key_id, KeyPatch(status="disabled"))
    await db.commit()
    invalidate_cache()
    return (await svc.key_out(db, [k]))[0]


# ---------------------------------------------------------------- models
@router.get("/models", response_model=list[ModelOut])
async def list_models(provider_id: UUID | None = None, _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    stmt = select(AIModel).order_by(AIModel.model_name)
    if provider_id:
        stmt = stmt.where(AIModel.provider_id == provider_id)
    return await svc.model_out(db, list((await db.execute(stmt)).scalars().all()))


@router.post("/models", response_model=ModelOut, status_code=201)
async def create_model(body: ModelIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    m = await svc.create_model(db, body)
    await db.commit()
    invalidate_cache()
    return (await svc.model_out(db, [m]))[0]


@router.patch("/models/{model_id}", response_model=ModelOut)
async def update_model(model_id: UUID, body: ModelPatch, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    m = await svc.update_model(db, model_id, body)
    await db.commit()
    invalidate_cache()
    return (await svc.model_out(db, [m]))[0]


@router.delete("/models/{model_id}", response_model=ModelOut)
async def disable_model(model_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    m = await svc.disable_model(db, model_id)
    await db.commit()
    invalidate_cache()
    return (await svc.model_out(db, [m]))[0]


@router.post("/models/{model_id}/test", response_model=ModelTestOut)
async def test_model(model_id: UUID, body: ModelTestIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    m = await svc.get_model(db, model_id)
    res, err, ms = await svc.run_probe(db, m, body.prompt, "model_test")
    if res is None:
        return ModelTestOut(error=err, latency_ms=ms)
    return ModelTestOut(text=res.text, latency_ms=res.latency_ms or ms, tokens_in=res.tokens_in, tokens_out=res.tokens_out, cost=res.cost)


# ---------------------------------------------------------------- routes
@router.get("/routes", response_model=list[RouteOut])
async def list_routes(_: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await svc.routes_out(db)


@router.put("/routes/{task}", response_model=RouteOut)
async def put_route(task: str, body: RoutePut, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    await svc.put_route(db, task, body)
    await db.commit()
    invalidate_cache()
    return (await svc.routes_out(db, task))[0]


@router.patch("/routes/{task}/enabled", response_model=RouteOut)
async def route_enabled(task: str, body: EnabledIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    await svc.set_route_enabled(db, task, body.enabled)
    await db.commit()
    invalidate_cache()
    return (await svc.routes_out(db, task))[0]


@router.post("/routes/{task}/simulate-failure", response_model=RouteSimOut)
async def simulate_route_failure(task: str, body: FailureIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db),
                                 redis=Depends(_redis)):
    return await svc.simulate_route_failure(db, redis, task, body.error_code, body.seconds)


# ---------------------------------------------------------------- safety, health, playground
@router.get("/safety")
async def get_safety(_: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await svc.safety(db)


@router.put("/safety")
async def put_safety(body: SafetyPut, p: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    await svc.put_safety(db, body, p.user_id)
    await db.commit()
    invalidate_cache()
    return await svc.safety(db)


@router.get("/health")
async def get_health(_: Principal = Depends(read), db: AsyncSession = Depends(get_db), redis=Depends(_redis)):
    return await svc.health(db, redis)


@router.post("/test")
async def playground(body: PlaygroundIn, _: Principal = Depends(write)):
    """Admin playground: one request through the real router, with the real fallback path in the answer."""
    ctx = dict(body.context)
    if ctx.get("force_model_id"):
        ctx["force_model_id"] = UUID(str(ctx["force_model_id"]))
    try:
        res = await ai_router.run(body.task, body.messages, response_schema=IntentExtraction if body.schema_ == "intent" else None, context=ctx)
    except ai_router.AIUnavailable as e:
        return {"unavailable": True, "reason": e.reason, "path": e.path, "request_id": e.request_id}
    parsed = res.parsed.model_dump() if hasattr(res.parsed, "model_dump") else res.parsed
    return {"unavailable": False, "text": res.text, "parsed": parsed, "provider": res.provider, "model": res.model, "tokens_in": res.tokens_in,
            "tokens_out": res.tokens_out, "cost": str(res.cost), "latency_ms": res.latency_ms, "fallback_depth": res.fallback_depth,
            "request_id": res.request_id, "path": res.path}
