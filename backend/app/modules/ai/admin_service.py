"""Admin operations for the AI platform. Every write goes through the ORM so the audit log records before/after
(encrypted keys are masked by the audit hook); callers invalidate the route cache after committing."""
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.security import decrypt_secret, encrypt_secret
from app.modules.ai import breaker
from app.modules.ai import router as ai_router
from app.modules.ai.admin_schemas import (
    KeyIn, KeyOut, KeyPatch, ModelIn, ModelOut, ModelPatch, ProviderIn, ProviderOut, ProviderPatch, RoutePut, StepIn,
)
from app.modules.ai.models import TASKS, AIModel, AIProvider, AIProviderKey, AIRoute, AIRouteStep, AIUsageLog
from app.modules.settings.models import SystemSetting

DEFAULT_BREAKER = {"threshold": 5, "window_seconds": 60, "cooldown_seconds": 30}
MOCK_MODELS = ("mock-primary", "mock-fast", "mock-weak")


def _month_start() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def breaker_cfg(db: AsyncSession) -> breaker.BreakerConfig:
    row = (await db.execute(select(SystemSetting.value).where(SystemSetting.key == "ai_breaker"))).first()
    return breaker.BreakerConfig.from_setting(row[0] if row else None)


# ---------------------------------------------------------------- providers
async def get_provider(db: AsyncSession, provider_id: UUID) -> AIProvider:
    p = await db.get(AIProvider, provider_id)
    if p is None:
        raise NotFoundError("Provider not found")
    return p


async def provider_out(db: AsyncSession, redis: Redis, rows: list[AIProvider]) -> list[ProviderOut]:
    ids = [r.id for r in rows]
    keys = dict((await db.execute(select(AIProviderKey.provider_id, func.count()).where(AIProviderKey.provider_id.in_(ids))
                                   .group_by(AIProviderKey.provider_id))).all()) if ids else {}
    models = dict((await db.execute(select(AIModel.provider_id, func.count()).where(AIModel.provider_id.in_(ids))
                                    .group_by(AIModel.provider_id))).all()) if ids else {}
    cfg = await breaker_cfg(db)
    out = []
    for r in rows:
        st = await breaker.state(redis, "provider", str(r.id), cfg)
        out.append(ProviderOut(id=r.id, name=r.name, kind=r.kind, base_url=r.base_url, status=r.status, rate_limit_rpm=r.rate_limit_rpm,
                               allow_pii=r.allow_pii, last_error=r.last_error, last_checked_at=r.last_checked_at, notes=r.notes,
                               key_count=keys.get(r.id, 0), model_count=models.get(r.id, 0), breaker=st))
    return out


async def create_provider(db: AsyncSession, body: ProviderIn) -> AIProvider:
    if (await db.execute(select(AIProvider.id).where(AIProvider.name == body.name))).first():
        raise ConflictError("NAME_EXISTS", "A provider with this name already exists")
    p = AIProvider(**body.model_dump(), status="disabled")
    db.add(p)
    await db.flush()
    return p


async def update_provider(db: AsyncSession, provider_id: UUID, body: ProviderPatch) -> AIProvider:
    p = await get_provider(db, provider_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != p.name and (await db.execute(select(AIProvider.id).where(AIProvider.name == data["name"]))).first():
        raise ConflictError("NAME_EXISTS", "A provider with this name already exists")
    for k, v in data.items():
        setattr(p, k, v)
    return p


async def _used_by_steps(db: AsyncSession, *, provider_id: UUID | None = None, model_id: UUID | None = None, key_id: UUID | None = None) -> list[str]:
    stmt = select(AIRoute.task).join(AIRouteStep, AIRouteStep.route_id == AIRoute.id).join(AIModel, AIModel.id == AIRouteStep.model_id)
    if provider_id:
        stmt = stmt.where(AIModel.provider_id == provider_id)
    if model_id:
        stmt = stmt.where(AIRouteStep.model_id == model_id)
    if key_id:
        stmt = stmt.where(AIRouteStep.key_id == key_id)
    return sorted({r[0] for r in (await db.execute(stmt)).all()})


async def disable_provider(db: AsyncSession, provider_id: UUID) -> AIProvider:
    p = await get_provider(db, provider_id)
    used = await _used_by_steps(db, provider_id=provider_id)
    if used:
        raise ConflictError("IN_USE", "This provider is used by a route; remove it from the chain first", {"tasks": used})
    p.status = "disabled"
    return p


async def run_probe(db: AsyncSession, model: AIModel, prompt: str, task: str):
    """One small request through the router pinned to a model. Never calls a provider directly."""
    t0 = time.perf_counter()
    try:
        res = await ai_router.run(task, [{"role": "user", "content": prompt}], context={"force_model_id": model.id})
        return res, None, int((time.perf_counter() - t0) * 1000)
    except ai_router.AIUnavailable as e:
        detail = "; ".join(f"{s.get('provider')}/{s.get('model')}: {s.get('outcome')}" for s in e.path) or e.reason
        return None, f"{e.reason}: {detail}", int((time.perf_counter() - t0) * 1000)


async def test_provider(db: AsyncSession, provider_id: UUID):
    p = await get_provider(db, provider_id)
    model = (await db.execute(select(AIModel).where(AIModel.provider_id == p.id, AIModel.status == "active")
                             .order_by(AIModel.created_at).limit(1))).scalar_one_or_none()
    if model is None:
        return False, 0, None, "Add an active model to this provider first"
    if p.status != "enabled":
        return False, 0, model.model_name, "The provider is disabled; enable it before testing the connection"
    res, err, ms = await run_probe(db, model, "ping", "provider_test")
    p.last_checked_at = datetime.now(UTC)
    p.last_error = None if res else (err or "unknown error")[:500]
    return res is not None, ms, model.model_name, err


async def set_fault(redis: Redis, provider_id: UUID, code: str, seconds: int) -> None:
    await redis.set(f"ai:fault:{provider_id}", code, ex=seconds)


async def clear_fault(redis: Redis, provider_id: UUID) -> None:
    await redis.delete(f"ai:fault:{provider_id}")
    await breaker.success(redis, "provider", str(provider_id))


async def load_models(db: AsyncSession, provider_id: UUID) -> list[str]:
    p = await get_provider(db, provider_id)
    names: list[str]
    if p.kind == "mock":
        names, caps = list(MOCK_MODELS), ["chat", "json", "multilingual"]
    elif p.kind == "openai_compatible":
        if not p.base_url:
            raise ValidationAppError("Set the provider base_url first")
        key = (await db.execute(select(AIProviderKey).where(AIProviderKey.provider_id == p.id, AIProviderKey.status == "active")
                                .order_by(AIProviderKey.created_at).limit(1))).scalar_one_or_none()
        headers = {"Authorization": f"Bearer {decrypt_secret(key.encrypted_key)}"} if key else {}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{p.base_url}/models", headers=headers)
                r.raise_for_status()
                data = r.json().get("data", [])
        except (httpx.HTTPError, ValueError) as e:
            raise ValidationAppError(f"Could not load models from the provider: {type(e).__name__}") from None
        names, caps = [str(m.get("id")) for m in data if m.get("id")], ["chat"]
    else:
        raise ValidationAppError("Enter model names manually for this provider kind")
    existing = {r[0] for r in (await db.execute(select(AIModel.model_name).where(AIModel.provider_id == p.id))).all()}
    added = [n for n in names if n not in existing][:200]
    for n in added:
        db.add(AIModel(provider_id=p.id, model_name=n, capabilities=caps, status="active"))
    await db.flush()
    return added


# ---------------------------------------------------------------- keys
async def get_key(db: AsyncSession, key_id: UUID) -> AIProviderKey:
    k = await db.get(AIProviderKey, key_id)
    if k is None:
        raise NotFoundError("Key not found")
    return k


async def key_out(db: AsyncSession, rows: list[AIProviderKey]) -> list[KeyOut]:
    if not rows:
        return []
    ids = [r.id for r in rows]
    spend = {kid: (Decimal(c), n) for kid, c, n in (await db.execute(
        select(AIUsageLog.key_id, func.coalesce(func.sum(AIUsageLog.cost), 0), func.count()).where(
            AIUsageLog.key_id.in_(ids), AIUsageLog.created_at >= _month_start()).group_by(AIUsageLog.key_id))).all()}
    names = dict((await db.execute(select(AIProvider.id, AIProvider.name).where(AIProvider.id.in_({r.provider_id for r in rows})))).all())
    return [KeyOut(id=r.id, provider_id=r.provider_id, provider_name=names.get(r.provider_id, ""), label=r.label, key_last4=r.key_last4,
                   status=r.status, last_used_at=r.last_used_at, monthly_budget=r.monthly_budget, weight=r.weight, last_error=r.last_error,
                   month_spend=spend.get(r.id, (Decimal("0"), 0))[0], month_requests=spend.get(r.id, (Decimal("0"), 0))[1]) for r in rows]


async def create_key(db: AsyncSession, body: KeyIn) -> AIProviderKey:
    await get_provider(db, body.provider_id)
    k = AIProviderKey(provider_id=body.provider_id, label=body.label, encrypted_key=encrypt_secret(body.api_key.strip()),
                      key_last4=body.api_key.strip()[-4:], status="active", monthly_budget=body.monthly_budget, weight=body.weight)
    db.add(k)
    await db.flush()
    return k


async def update_key(db: AsyncSession, key_id: UUID, body: KeyPatch) -> AIProviderKey:
    k = await get_key(db, key_id)
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(k, f, v)
    if body.status == "active":
        k.last_error = None
    return k


async def rotate_key(db: AsyncSession, key_id: UUID, api_key: str) -> AIProviderKey:
    k = await get_key(db, key_id)
    k.encrypted_key, k.key_last4, k.status, k.last_error = encrypt_secret(api_key.strip()), api_key.strip()[-4:], "active", None
    return k


# ---------------------------------------------------------------- models
async def get_model(db: AsyncSession, model_id: UUID) -> AIModel:
    m = await db.get(AIModel, model_id)
    if m is None:
        raise NotFoundError("Model not found")
    return m


async def model_out(db: AsyncSession, rows: list[AIModel]) -> list[ModelOut]:
    names = dict((await db.execute(select(AIProvider.id, AIProvider.name).where(AIProvider.id.in_({r.provider_id for r in rows})))).all()) if rows else {}
    return [ModelOut(id=r.id, provider_id=r.provider_id, provider_name=names.get(r.provider_id, ""), model_name=r.model_name,
                     capabilities=list(r.capabilities or []), context_window=r.context_window, input_price=r.input_price,
                     output_price=r.output_price, status=r.status) for r in rows]


async def create_model(db: AsyncSession, body: ModelIn) -> AIModel:
    await get_provider(db, body.provider_id)
    if (await db.execute(select(AIModel.id).where(AIModel.provider_id == body.provider_id, AIModel.model_name == body.model_name))).first():
        raise ConflictError("MODEL_EXISTS", "This provider already has a model with that name")
    m = AIModel(**body.model_dump(), status="active")
    db.add(m)
    await db.flush()
    return m


async def update_model(db: AsyncSession, model_id: UUID, body: ModelPatch) -> AIModel:
    m = await get_model(db, model_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("status") == "disabled":
        used = await _used_by_steps(db, model_id=model_id)
        if used:
            raise ConflictError("IN_USE", "This model is used by a route; remove it from the chain first", {"tasks": used})
    for k, v in data.items():
        setattr(m, k, v)
    return m


async def disable_model(db: AsyncSession, model_id: UUID) -> AIModel:
    return await update_model(db, model_id, ModelPatch(status="disabled"))


# ---------------------------------------------------------------- routes
async def routes_out(db: AsyncSession, task: str | None = None) -> list[dict]:
    stmt = select(AIRoute).order_by(AIRoute.task)
    if task:
        stmt = stmt.where(AIRoute.task == task)
    routes = list((await db.execute(stmt)).scalars().all())
    out = []
    for r in routes:
        rows = (await db.execute(select(AIRouteStep, AIModel, AIProvider).join(AIModel, AIModel.id == AIRouteStep.model_id)
                                 .join(AIProvider, AIProvider.id == AIModel.provider_id).where(AIRouteStep.route_id == r.id)
                                 .order_by(AIRouteStep.priority))).all()
        out.append({"task": r.task, "description": r.description, "enabled": r.enabled, "fallback_on_refusal": r.fallback_on_refusal,
                    "steps": [{"id": s.id, "priority": s.priority, "model_id": s.model_id, "model_name": m.model_name, "provider_name": p.name,
                               "key_id": s.key_id, "key_ids": list(s.key_ids or []), "key_strategy": s.key_strategy, "timeout_ms": s.timeout_ms,
                               "max_retries": s.max_retries, "temperature": s.temperature, "max_tokens": s.max_tokens,
                               "conditions": s.conditions or {}} for s, m, p in rows]})
    return out


async def put_route(db: AsyncSession, task: str, body: RoutePut) -> None:
    """Replace the chain. Validates every step: active model, key of the model's own provider, known condition keys."""
    if task not in TASKS:
        raise NotFoundError("Unknown AI task")
    route = (await db.execute(select(AIRoute).where(AIRoute.task == task))).scalar_one_or_none()
    if route is None:
        route = AIRoute(task=task, enabled=True, fallback_on_refusal=True)
        db.add(route)
        await db.flush()
    checked: list[tuple[StepIn, AIModel]] = []
    for i, s in enumerate(body.steps, start=1):
        m = await db.get(AIModel, s.model_id)
        if m is None:
            raise ValidationAppError(f"Step {i}: model not found")
        if m.status != "active":
            raise ValidationAppError(f"Step {i}: model {m.model_name} is not active")
        for kid in ([s.key_id] if s.key_id else []) + list(s.key_ids):
            k = await db.get(AIProviderKey, kid)
            if k is None or k.provider_id != m.provider_id:
                raise ValidationAppError(f"Step {i}: a key does not belong to the provider of model {m.model_name}")
        checked.append((s, m))
    await db.execute(delete(AIRouteStep).where(AIRouteStep.route_id == route.id))
    await db.flush()
    for i, (s, _) in enumerate(checked, start=1):
        db.add(AIRouteStep(route_id=route.id, priority=i, model_id=s.model_id, key_id=s.key_id, key_ids=[str(k) for k in s.key_ids],
                           key_strategy=s.key_strategy, timeout_ms=s.timeout_ms, max_retries=s.max_retries, temperature=s.temperature,
                           max_tokens=s.max_tokens, conditions=s.conditions))
    if body.enabled is not None:
        route.enabled = body.enabled
    if body.fallback_on_refusal is not None:
        route.fallback_on_refusal = body.fallback_on_refusal
    await db.flush()


async def set_route_enabled(db: AsyncSession, task: str, enabled: bool) -> None:
    route = (await db.execute(select(AIRoute).where(AIRoute.task == task))).scalar_one_or_none()
    if route is None:
        raise NotFoundError("Route not found")
    route.enabled = enabled


async def simulate_route_failure(db: AsyncSession, redis: Redis, task: str, code: str, seconds: int) -> dict:
    """Forces the PRIMARY step's provider to fail, sends a probe through the router so the fallback can be seen working,
    and always clears the fault again."""
    first = (await db.execute(select(AIModel.provider_id).join(AIRouteStep, AIRouteStep.model_id == AIModel.id)
                              .join(AIRoute, AIRoute.id == AIRouteStep.route_id).where(AIRoute.task == task)
                              .order_by(AIRouteStep.priority).limit(1))).first()
    if first is None:
        raise ValidationAppError("This route has no steps to simulate")
    pid = first[0]
    await set_fault(redis, pid, code, seconds)
    try:
        try:
            res = await ai_router.run(task, [{"role": "user", "content": "ping"}])
            return {"used": {"provider": res.provider, "model": res.model}, "fallback_depth": res.fallback_depth, "path": res.path, "unavailable": False}
        except ai_router.AIUnavailable as e:
            return {"used": None, "fallback_depth": max(0, len(e.path) - 1), "path": e.path, "unavailable": True}
    finally:
        await clear_fault(redis, pid)


# ---------------------------------------------------------------- safety / health
async def _setting(db: AsyncSession, key: str, default: Any):
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    return row.value if row is not None and row.value is not None else default


async def _set_setting(db: AsyncSession, key: str, value: Any, user_id: UUID | None) -> None:
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=key, value=value, updated_by=user_id))
    else:
        row.value, row.updated_by = value, user_id


async def safety(db: AsyncSession) -> dict:
    routes = await routes_out(db)
    providers = (await db.execute(select(AIProvider).order_by(AIProvider.name))).scalars().all()
    br = {**DEFAULT_BREAKER, **(await _setting(db, "ai_breaker", {}))}
    return {"kill_switch": (await _setting(db, "ai_kill_switch", False)) is True, "log_bodies": (await _setting(db, "ai_log_bodies", False)) is True,
            "log_retention_days": int(await _setting(db, "ai_log_retention_days", 30)), "breaker": br,
            "tasks": [{"task": r["task"], "enabled": r["enabled"]} for r in routes],
            "providers": [{"id": p.id, "name": p.name, "allow_pii": p.allow_pii} for p in providers]}


async def put_safety(db: AsyncSession, body, user_id: UUID | None) -> None:
    if body.kill_switch is not None:
        await _set_setting(db, "ai_kill_switch", body.kill_switch, user_id)
    if body.log_bodies is not None:
        await _set_setting(db, "ai_log_bodies", body.log_bodies, user_id)
    if body.log_retention_days is not None:
        await _set_setting(db, "ai_log_retention_days", body.log_retention_days, user_id)
    if body.breaker is not None:
        await _set_setting(db, "ai_breaker", body.breaker.model_dump(), user_id)


async def health(db: AsyncSession, redis: Redis) -> dict:
    cfg = await breaker_cfg(db)
    kill = (await _setting(db, "ai_kill_switch", False)) is True
    providers = (await db.execute(select(AIProvider).order_by(AIProvider.name))).scalars().all()
    states = {p.id: await breaker.state(redis, "provider", str(p.id), cfg) for p in providers}
    failed_keys = (await db.execute(select(func.count()).select_from(AIProviderKey).where(AIProviderKey.status == "failed"))).scalar_one()
    tasks = []
    by_id = {p.id: p for p in providers}
    for r in await routes_out(db):
        if kill or not r["enabled"]:
            state = "off"
        elif not r["steps"]:
            state = "unconfigured"
        else:
            steps = (await db.execute(select(AIRouteStep, AIModel).join(AIModel, AIModel.id == AIRouteStep.model_id)
                                      .join(AIRoute, AIRoute.id == AIRouteStep.route_id).where(AIRoute.task == r["task"])
                                      .order_by(AIRouteStep.priority))).all()
            prim = by_id[steps[0][1].provider_id]
            bad_key = False
            for s, _m in steps:
                ids = [UUID(str(i)) for i in (s.key_ids or [])] or ([s.key_id] if s.key_id else [])
                if ids and (await db.execute(select(func.count()).select_from(AIProviderKey).where(AIProviderKey.id.in_(ids), AIProviderKey.status == "failed"))).scalar_one():
                    bad_key = True
            state = "degraded" if (states[prim.id] != "closed" or prim.status != "enabled" or bad_key or any(
                states[by_id[m.provider_id].id] != "closed" for _s, m in steps[1:])) else "ok"
        tasks.append({"task": r["task"], "state": state})
    return {"kill_switch": kill, "failed_keys": failed_keys, "tasks": tasks,
            "providers": [{"id": p.id, "name": p.name, "status": p.status, "breaker": states[p.id], "last_error": p.last_error} for p in providers]}
