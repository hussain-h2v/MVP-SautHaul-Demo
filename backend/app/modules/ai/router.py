"""The single AI router. NO other code calls an AI provider: everything goes through `run(...)`.

run(task, messages, tools=None, response_schema=None, context=None)
  1. global / per-task kill switch -> AIUnavailable (callers degrade to fixed menus)
  2. walk the task's route chain; per step: skip when provider/model disabled, condition not met, breaker open, local
     rate limit hit, budget exhausted, or no healthy key; otherwise call the provider (retries on transient errors)
  3. fall back on timeout, 429, 5xx, network, invalid structured output (after one automatic repair attempt), refusal
     (when the route allows it) and exhausted budget; an auth error disables the key, alerts admins and falls back
  4. every request is logged to ai_usage_logs with its full fallback path
Capacity decisions are never made here: AI may read, explain, classify and recommend only."""
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select, update

from app.core import metrics
from app.core.config import get_settings
from app.core.context import current_trace_id
from app.core.db import async_session_factory
from app.core.idempotency import get_redis
from app.core.outbox import emit
from app.core.security import decrypt_secret
from app.modules.ai import breaker, budgets
from app.modules.ai.clients import base
from app.modules.ai.clients.base import CallRequest, ProviderError
from app.modules.ai.clients.litellm_client import LiteLLMClient
from app.modules.ai.clients.mock_client import REPAIR_MARKER, MockClient
from app.modules.ai.config import KeyCfg, RouteCfg, StepCfg, load_route, load_step_for_model
from app.modules.ai.models import AIProvider, AIProviderKey, AIUsageLog
from app.modules.ai.privacy import Masker, redact
from app.modules.settings import service as settings_service


class AIUnavailable(Exception):
    """No step could answer (or AI is switched off). Callers must degrade gracefully: fixed menus, skipped insights."""

    def __init__(self, reason: str, request_id: str, path: list[dict]) -> None:
        self.reason, self.request_id, self.path = reason, request_id, path
        super().__init__(f"AI unavailable ({reason})")


@dataclass
class AIResult:
    text: str
    parsed: Any = None
    tool_calls: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: Decimal = Decimal("0")
    latency_ms: int = 0
    fallback_depth: int = 0
    request_id: str = ""
    path: list[dict] = field(default_factory=list)


_mock, _litellm = MockClient(), LiteLLMClient()


def _client(kind: str):
    return _mock if kind == "mock" else _litellm


# ---------------------------------------------------------------- helpers
def _extract_json(text: str) -> Any:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0] or [0])
    return json.loads(t[start:])


def _parse(text: str, schema: type[BaseModel] | dict | None) -> Any:
    if schema is None:
        return None
    data = _extract_json(text)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_validate(data)
    return data


def _condition_ok(cond: dict, ctx: dict, messages: list[dict]) -> bool:
    if not cond:
        return True
    if cond.get("languages") and ctx.get("language") not in cond["languages"]:
        return False
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    if cond.get("max_input_chars") and chars > int(cond["max_input_chars"]):
        return False
    if cond.get("min_input_chars") and chars < int(cond["min_input_chars"]):
        return False
    return True


def _cost(step: StepCfg, tin: int, tout: int) -> Decimal:
    return (Decimal(tin) * step.input_price + Decimal(tout) * step.output_price) / Decimal(1_000_000)


async def _breaker_cfg(db) -> breaker.BreakerConfig:
    return breaker.BreakerConfig.from_setting(await settings_service.get_value(db, "ai_breaker", None))


async def _pick_key(redis: Redis, step: StepCfg, db, task: str, now: datetime, bcfg: breaker.BreakerConfig,
                    tried: set) -> tuple[KeyCfg | None, str | None]:
    """Healthy key by the step's strategy. (None, None) when the provider needs no key (mock, local servers)."""
    if not step.keys:
        return (None, None) if step.provider_kind in ("mock", "openai_compatible") else (None, "no_key")
    healthy: list[KeyCfg] = []
    reason = "no_healthy_key"
    for k in step.keys:
        if k.status != "active" or k.id in tried:
            continue
        if not await breaker.allow(redis, "key", str(k.id), bcfg, now.timestamp()):
            reason = "key_circuit_open"
            continue
        if await budgets.exhausted(db, task=task, provider_id=step.provider_id, provider_name=step.provider_name, key=k, now=now):
            reason = "budget_exhausted"
            continue
        healthy.append(k)
    if not healthy:
        return None, reason
    if step.key_strategy == "weighted":
        return random.choices(healthy, weights=[max(1, k.weight) for k in healthy], k=1)[0], None
    if step.key_strategy == "round_robin" and len(healthy) > 1:
        n = await redis.incr(f"ai:rr:{step.id}")
        return healthy[(n - 1) % len(healthy)], None
    return healthy[0], None


async def _local_rate_limited(redis: Redis, step: StepCfg, now: datetime) -> bool:
    if not step.rate_limit_rpm:
        return False
    key = f"ai:rpm:{step.provider_id}:{int(now.timestamp() // 60)}"
    n = await redis.incr(key)
    if n == 1:
        await redis.expire(key, 90)
    return n > step.rate_limit_rpm


async def _forced_fault(redis: Redis, step: StepCfg) -> str | None:
    """Admin 'Simulate failure' for a provider: forces an error code for a short while."""
    v = await redis.get(f"ai:fault:{step.provider_id}")
    return v if isinstance(v, str) else (v.decode() if v else None)


async def _alert(event: str, title: str, body: str, **payload) -> None:
    async with async_session_factory() as db:
        emit(db, event, {"title": title, "body": body, **payload})
        await db.commit()


# ---------------------------------------------------------------- the router
async def run(task: str, messages: list[dict], *, tools: list[dict] | None = None, response_schema: type[BaseModel] | dict | None = None,
              context: dict | None = None, now: datetime | None = None) -> AIResult:
    ctx = dict(context or {})
    now = now or datetime.now(UTC)
    request_id = uuid.uuid4().hex[:20]
    path: list[dict] = []
    started = time.perf_counter()
    redis = get_redis()
    try:
        async with async_session_factory() as db:
            if await settings_service.get_value(db, "ai_kill_switch", False) is True:
                await _log(now, task, request_id, None, None, None, 0, 0, Decimal("0"), 0, "disabled", 0, "KILL_SWITCH", path, messages, "")
                raise AIUnavailable("KILL_SWITCH", request_id, path)
            if ctx.get("force_model_id"):
                one = await load_step_for_model(db, ctx["force_model_id"])
                route = RouteCfg(task, True, False, [one] if one else [])
            else:
                route = await load_route(db, task)
            if route is None or not route.enabled:
                await _log(now, task, request_id, None, None, None, 0, 0, Decimal("0"), 0, "disabled", 0, "TASK_DISABLED" if route else "NO_ROUTE", path, messages, "")
                raise AIUnavailable("TASK_DISABLED" if route else "NO_ROUTE", request_id, path)
            bcfg = await _breaker_cfg(db)
            for depth, step in enumerate(route.steps):
                entry = {"step": step.priority, "provider": step.provider_name, "model": step.model_name}
                path.append(entry)
                if not step.provider_enabled or not step.model_active:
                    entry["outcome"] = "skipped:disabled"
                    continue
                if not ctx.get("force_model_id") and not _condition_ok(step.conditions, ctx, messages):
                    entry["outcome"] = "skipped:condition"
                    continue
                if await _forced_fault(redis, step):
                    code = await _forced_fault(redis, step)
                    entry["outcome"] = f"error:{code}"
                    entry["forced"] = True
                    await breaker.failure(redis, "provider", str(step.provider_id), bcfg, now.timestamp())
                    continue
                if not await breaker.allow(redis, "provider", str(step.provider_id), bcfg, now.timestamp()):
                    entry["outcome"] = "skipped:circuit_open"
                    continue
                if await _local_rate_limited(redis, step, now):
                    entry["outcome"] = "skipped:rate_limited_locally"
                    continue
                if await budgets.exhausted(db, task=task, provider_id=step.provider_id, provider_name=step.provider_name, key=None, now=now):
                    entry["outcome"] = "skipped:budget_exhausted"
                    continue
                result = await _run_step(db, redis, step, route, task, messages, tools, response_schema, ctx, now, bcfg, entry)
                if result is None:
                    continue
                result.fallback_depth, result.request_id = depth, request_id
                result.path = path
                result.latency_ms = int((time.perf_counter() - started) * 1000)
                await _log(now, task, request_id, step, result.provider, result.model, result.tokens_in, result.tokens_out, result.cost,
                           result.latency_ms, "ok", depth, None, path, messages, result.text)
                async with async_session_factory() as db2:
                    await budgets.check_alerts(db2, redis, task=task, provider_id=step.provider_id, provider_name=step.provider_name,
                                               key_id=entry.get("key_id") and uuid.UUID(entry["key_id"]), now=now)
                    await db2.commit()
                metrics.AI_REQUESTS.labels(task, "ok").inc()
                return result
            latency = int((time.perf_counter() - started) * 1000)
            await _log(now, task, request_id, None, None, None, 0, 0, Decimal("0"), latency, "failed", max(0, len(path) - 1), "ALL_STEPS_FAILED", path, messages, "")
            metrics.AI_REQUESTS.labels(task, "failed").inc()
            raise AIUnavailable("ALL_STEPS_FAILED", request_id, path)
    finally:
        await redis.aclose()


async def run_or_none(task: str, messages: list[dict], **kw) -> AIResult | None:
    """Graceful degradation helper: AI is a nice-to-have, never a dependency of scheduling or booking."""
    try:
        return await run(task, messages, **kw)
    except AIUnavailable:
        return None


async def _run_step(db, redis: Redis, step: StepCfg, route: RouteCfg, task: str, messages, tools, schema, ctx: dict, now: datetime,
                    bcfg: breaker.BreakerConfig, entry: dict) -> AIResult | None:
    masker = None if step.allow_pii else Masker(ctx.get("pii_names"))
    sent = masker.mask_messages(messages) if masker else messages
    tried: set = set()
    for _attempt_key in range(max(1, len(step.keys))):
        key, why = await _pick_key(redis, step, db, task, now, bcfg, tried)
        if key is None and why:
            entry["outcome"] = f"skipped:{why}"
            return None
        if key is not None:
            tried.add(key.id)
            entry["key_id"] = str(key.id)
        api_key = decrypt_secret(key.encrypted_key) if key else None
        error_code: str | None = None
        for attempt in range(step.max_retries + 1):
            req = CallRequest(kind=step.provider_kind, base_url=step.base_url, model_name=step.model_name, api_key=api_key,
                              messages=sent, tools=tools, json_mode=schema is not None, temperature=step.temperature,
                              max_tokens=step.max_tokens, timeout_s=step.timeout_ms / 1000, attempt=attempt)
            t0 = time.perf_counter()
            try:
                resp = await _client(step.provider_kind).complete(req)
                parsed = None
                if schema is not None:
                    try:
                        parsed = _parse(resp.text, schema)
                    except (ValueError, ValidationError) as first:
                        repair = [*sent, {"role": "assistant", "content": resp.text},
                                  {"role": "user", "content": f"{REPAIR_MARKER} matching the requested schema, no prose. Error: {str(first)[:200]}"}]
                        resp2 = await _client(step.provider_kind).complete(CallRequest(
                            kind=step.provider_kind, base_url=step.base_url, model_name=step.model_name, api_key=api_key, messages=repair,
                            tools=tools, json_mode=True, temperature=0.0, max_tokens=step.max_tokens, timeout_s=step.timeout_ms / 1000, attempt=attempt))
                        resp.tokens_in += resp2.tokens_in
                        resp.tokens_out += resp2.tokens_out
                        try:
                            parsed, resp.text = _parse(resp2.text, schema), resp2.text
                            entry["repaired"] = True
                        except (ValueError, ValidationError):
                            raise ProviderError(base.INVALID_OUTPUT, "unparsable after one repair attempt") from None
                text = masker.unmask(resp.text) if masker else resp.text
                if masker and isinstance(parsed, BaseModel):
                    parsed = type(parsed).model_validate_json(masker.unmask(parsed.model_dump_json()))
                elif masker and isinstance(parsed, dict):
                    parsed = json.loads(masker.unmask(json.dumps(parsed)))
                await breaker.success(redis, "provider", str(step.provider_id))
                if key:
                    await breaker.success(redis, "key", str(key.id))
                    await db.execute(update(AIProviderKey).where(AIProviderKey.id == key.id).values(last_used_at=now))
                    await db.commit()
                entry["outcome"] = "ok"
                entry["ms"] = int((time.perf_counter() - t0) * 1000)
                return AIResult(text=text, parsed=parsed, tool_calls=resp.tool_calls, provider=step.provider_name, model=step.model_name,
                                tokens_in=resp.tokens_in, tokens_out=resp.tokens_out, cost=_cost(step, resp.tokens_in, resp.tokens_out))
            except ProviderError as e:
                error_code = e.code
                entry["outcome"] = f"error:{e.code}"
                entry["ms"] = int((time.perf_counter() - t0) * 1000)
                entry["message"] = e.message[:160]
                if e.code in base.RETRYABLE and attempt < step.max_retries:
                    continue
                break
        # the step failed on this key
        opened = await breaker.failure(redis, "provider", str(step.provider_id), bcfg, now.timestamp())
        if opened:
            await _alert("ai.provider_failure", f"AI provider {step.provider_name} is failing",
                         f"Circuit breaker opened after repeated {error_code} errors; requests fall back to the next step.",
                         provider=step.provider_name)
        if key is not None:
            await breaker.failure(redis, "key", str(key.id), bcfg, now.timestamp())
        if error_code == base.AUTH and key is not None:
            await db.execute(update(AIProviderKey).where(AIProviderKey.id == key.id).values(status="failed", last_error="authentication failed"))
            await db.execute(update(AIProvider).where(AIProvider.id == step.provider_id).values(last_error="authentication failed", last_checked_at=now))
            await db.commit()
            await _alert("ai.key_disabled", f"AI key '{key.label}' disabled", f"{step.provider_name} rejected the key (authentication error).",
                         provider=step.provider_name, key=key.label)
            from app.modules.ai.config import invalidate_cache
            invalidate_cache()
        if error_code == base.REFUSAL and not route.fallback_on_refusal:
            raise AIUnavailable("REFUSAL", "", [entry])
        if error_code == base.RATE_LIMIT and len(step.keys) > 1:
            continue  # try the next key of the pool before falling back
        return None
    return None


async def _log(now: datetime, task: str, request_id: str, step: StepCfg | None, provider: str | None, model: str | None, tin: int, tout: int,
               cost: Decimal, latency: int, status: str, depth: int, error: str | None, path: list[dict], messages: list[dict],
               response: str) -> None:
    async with async_session_factory() as db:
        bodies = await settings_service.get_value(db, "ai_log_bodies", False) is True
        key_id = None
        for e in reversed(path):
            if e.get("outcome") == "ok" and e.get("key_id"):
                key_id = uuid.UUID(e["key_id"])
        db.add(AIUsageLog(
            request_id=request_id, task=task, provider=provider or (step.provider_name if step else None), model=model,
            key_id=key_id, tokens_in=tin, tokens_out=tout, cost=cost, latency_ms=latency, status=status, fallback_depth=depth,
            error_code=error or next((e["outcome"].split(":", 1)[1] for e in reversed(path) if str(e.get("outcome", "")).startswith("error:")), None),
            trace_id=current_trace_id.get(), path=[{k: v for k, v in e.items() if k != "message"} for e in path],
            prompt_redacted=redact(json.dumps(messages, ensure_ascii=False))[:6000] if bodies else None,
            response_redacted=redact(response)[:6000] if bodies and response else None, created_at=now))
        await db.commit()


_ = (select, get_settings)
