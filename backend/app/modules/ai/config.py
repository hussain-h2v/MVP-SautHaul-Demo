"""Loads a task's route (with its steps, models, providers and keys) into plain dataclasses so the router never touches
ORM objects while calling a provider."""
import time
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai.models import AIModel, AIProvider, AIProviderKey, AIRoute, AIRouteStep


@dataclass
class KeyCfg:
    id: UUID
    label: str
    encrypted_key: str
    status: str
    monthly_budget: Decimal | None
    weight: int


@dataclass
class StepCfg:
    id: UUID
    priority: int
    provider_id: UUID
    provider_name: str
    provider_kind: str
    base_url: str | None
    provider_enabled: bool
    allow_pii: bool
    rate_limit_rpm: int | None
    model_id: UUID
    model_name: str
    model_active: bool
    input_price: Decimal
    output_price: Decimal
    keys: list[KeyCfg]
    key_strategy: str
    timeout_ms: int
    max_retries: int
    temperature: float
    max_tokens: int
    conditions: dict = field(default_factory=dict)


@dataclass
class RouteCfg:
    task: str
    enabled: bool
    fallback_on_refusal: bool
    steps: list[StepCfg]


_cache: dict[str, tuple[float, RouteCfg | None]] = {}
CACHE_TTL = 5.0


def invalidate_cache() -> None:
    _cache.clear()


async def load_route(db: AsyncSession, task: str) -> RouteCfg | None:
    use_cache = get_settings().env != "test"
    if use_cache and task in _cache and time.monotonic() - _cache[task][0] < CACHE_TTL:
        return _cache[task][1]
    route = (await db.execute(select(AIRoute).where(AIRoute.task == task))).scalar_one_or_none()
    cfg: RouteCfg | None = None
    if route is not None:
        rows = (await db.execute(
            select(AIRouteStep, AIModel, AIProvider).join(AIModel, AIModel.id == AIRouteStep.model_id)
            .join(AIProvider, AIProvider.id == AIModel.provider_id).where(AIRouteStep.route_id == route.id)
            .order_by(AIRouteStep.priority))).all()
        provider_ids = {p.id for _, _, p in rows}
        all_keys = list((await db.execute(select(AIProviderKey).where(AIProviderKey.provider_id.in_(provider_ids)))).scalars().all()) if provider_ids else []
        by_id = {k.id: k for k in all_keys}
        steps: list[StepCfg] = []
        for step, model, prov in rows:
            wanted = [UUID(str(i)) for i in (step.key_ids or [])] or ([step.key_id] if step.key_id else [])
            pool = [by_id[i] for i in wanted if i in by_id] if wanted else [k for k in all_keys if k.provider_id == prov.id]
            steps.append(StepCfg(
                id=step.id, priority=step.priority, provider_id=prov.id, provider_name=prov.name, provider_kind=prov.kind,
                base_url=prov.base_url, provider_enabled=prov.status == "enabled", allow_pii=prov.allow_pii,
                rate_limit_rpm=prov.rate_limit_rpm, model_id=model.id, model_name=model.model_name, model_active=model.status == "active",
                input_price=model.input_price, output_price=model.output_price,
                keys=[KeyCfg(k.id, k.label, k.encrypted_key, k.status, k.monthly_budget, k.weight) for k in pool],
                key_strategy=step.key_strategy, timeout_ms=step.timeout_ms, max_retries=step.max_retries,
                temperature=step.temperature, max_tokens=step.max_tokens, conditions=step.conditions or {}))
        cfg = RouteCfg(task, route.enabled, route.fallback_on_refusal, steps)
    if use_cache:
        _cache[task] = (time.monotonic(), cfg)
    return cfg


async def load_step_for_model(db: AsyncSession, model_id: UUID) -> StepCfg | None:
    """An ad-hoc single step for one model (evaluations, model test prompts): ignores routes and conditions."""
    row = (await db.execute(select(AIModel, AIProvider).join(AIProvider, AIProvider.id == AIModel.provider_id)
                            .where(AIModel.id == model_id))).first()
    if row is None:
        return None
    model, prov = row
    keys = list((await db.execute(select(AIProviderKey).where(AIProviderKey.provider_id == prov.id))).scalars().all())
    return StepCfg(
        id=model.id, priority=0, provider_id=prov.id, provider_name=prov.name, provider_kind=prov.kind, base_url=prov.base_url,
        provider_enabled=prov.status == "enabled", allow_pii=prov.allow_pii, rate_limit_rpm=prov.rate_limit_rpm, model_id=model.id,
        model_name=model.model_name, model_active=model.status == "active", input_price=model.input_price,
        output_price=model.output_price, keys=[KeyCfg(k.id, k.label, k.encrypted_key, k.status, k.monthly_budget, k.weight) for k in keys],
        key_strategy="round_robin", timeout_ms=20000, max_retries=0, temperature=0.0, max_tokens=800, conditions={})
