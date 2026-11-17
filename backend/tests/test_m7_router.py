"""Milestone 7: the AI router with mock providers (every failure path), breaker, budgets, key pools, privacy, degradation."""
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import select, text

from app.core.db import async_session_factory
from app.core.idempotency import get_redis
from app.core.security import decrypt_secret, encrypt_secret
from app.modules.ai import breaker, router
from app.modules.ai.clients.base import CallResponse
from app.modules.ai.clients.mock_client import MockClient, classify
from app.modules.ai.models import AIBudget, AIModel, AIProvider, AIProviderKey, AIRoute, AIRouteStep, AIUsageLog
from app.modules.ai.privacy import Masker
from app.modules.ai.router import AIUnavailable, run, run_or_none
from app.modules.notifications.models import OutboxEvent
from app.modules.settings.models import SystemSetting
from tests.conftest import login

NOW = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)
MSG = [{"role": "system", "content": "Classify."}, {"role": "user", "content": "Truck kharab ho gaya, 2 ghante late"}]


class Intent(BaseModel):
    intent: str
    delay_minutes: int | None = None


@pytest_asyncio.fixture(autouse=True)
async def clean_ai_state():
    r = get_redis()
    try:
        keys = [k async for k in r.scan_iter("cb:*")] + [k async for k in r.scan_iter("ai:*")]
        if keys:
            await r.delete(*keys)
    finally:
        await r.aclose()
    yield


class Recorder:
    """Wraps the mock client so tests can see exactly what a provider would have received."""

    def __init__(self):
        self.calls = []
        self.inner = MockClient()
        self.fail_for_key: dict[str, str] = {}

    async def complete(self, req):
        self.calls.append(req)
        if req.api_key in self.fail_for_key:
            from app.modules.ai.clients.base import ProviderError

            raise ProviderError(self.fail_for_key[req.api_key], "forced for key")
        return await self.inner.complete(req)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(router, "_mock", r)
    return r


async def build(task="intent_classify", steps=(), *, enabled=True, fallback_on_refusal=True, providers=None):
    """steps: dicts {model, provider?, keys?: [plaintext], strategy, retries, in_price, out_price, conditions, rpm, allow_pii}"""
    ids = {}
    async with async_session_factory() as db:
        route = AIRoute(task=task, description="t", enabled=enabled, fallback_on_refusal=fallback_on_refusal)
        db.add(route)
        await db.flush()
        provs: dict[str, AIProvider] = {}
        for i, s in enumerate(steps, start=1):
            pname = s.get("provider", f"mock{i}")
            if pname not in provs:
                provs[pname] = AIProvider(name=pname, kind="mock", status="enabled", allow_pii=s.get("allow_pii", True),
                                          rate_limit_rpm=s.get("rpm"))
                db.add(provs[pname])
                await db.flush()
            p = provs[pname]
            m = AIModel(provider_id=p.id, model_name=s["model"], capabilities=["chat", "json"], input_price=Decimal(str(s.get("in_price", 0))),
                        output_price=Decimal(str(s.get("out_price", 0))), status="active")
            db.add(m)
            await db.flush()
            key_ids = []
            for j, plain in enumerate(s.get("keys", [])):
                k = AIProviderKey(provider_id=p.id, label=f"k{i}{j}", encrypted_key=encrypt_secret(plain), key_last4=plain[-4:],
                                  monthly_budget=s.get("key_budget"), weight=(s.get("weights") or [1] * 9)[j])
                db.add(k)
                await db.flush()
                key_ids.append(str(k.id))
                ids.setdefault("keys", []).append(k.id)
            st = AIRouteStep(route_id=route.id, priority=i, model_id=m.id, key_ids=key_ids, key_strategy=s.get("strategy", "single"),
                             timeout_ms=1000, max_retries=s.get("retries", 0), temperature=0.0, max_tokens=200,
                             conditions=s.get("conditions", {}))
            db.add(st)
            ids.setdefault("providers", []).append(p.id)
            ids.setdefault("models", []).append(m.id)
        await db.commit()
        ids["route"] = route.id
    return ids


async def logs(task="intent_classify"):
    async with async_session_factory() as db:
        return list((await db.execute(select(AIUsageLog).where(AIUsageLog.task == task).order_by(AIUsageLog.created_at))).scalars().all())


async def outbox(kind):
    async with async_session_factory() as db:
        return list((await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == kind))).scalars().all())


async def set_setting(key, value):
    async with async_session_factory() as db:
        s = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
        if s:
            s.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
        await db.commit()


# ---------------------------------------------------------------- success, cost, logging
async def test_success_logs_usage_cost_and_key_last_used(rec):
    ids = await build(steps=[{"model": "mock-primary", "keys": ["sk-test-aaaa1111"], "in_price": 3, "out_price": 15}])
    res = await run("intent_classify", MSG, response_schema=Intent, context={"language": "hi"}, now=NOW)
    assert res.parsed.intent == "report_delay" and res.parsed.delay_minutes == 120 and res.fallback_depth == 0
    assert res.provider == "mock1" and res.model == "mock-primary" and res.tokens_in > 0 and res.tokens_out > 0
    assert res.cost == (Decimal(res.tokens_in) * 3 + Decimal(res.tokens_out) * 15) / 1_000_000 and res.cost > 0
    [row] = await logs()
    assert row.status == "ok" and row.cost == res.cost and row.request_id == res.request_id and row.key_id == ids["keys"][0]
    assert row.prompt_redacted is None and [p["outcome"] for p in row.path] == ["ok"]
    async with async_session_factory() as db:
        assert (await db.get(AIProviderKey, ids["keys"][0])).last_used_at is not None
    assert rec.calls[0].api_key == "sk-test-aaaa1111"  # decrypted only at call time


async def test_keys_are_encrypted_at_rest(rec):
    await build(steps=[{"model": "mock-primary", "keys": ["sk-secret-ZZZZ9999"]}])
    async with async_session_factory() as db:
        stored = (await db.execute(text("SELECT encrypted_key, key_last4 FROM ai_provider_keys"))).one()
        assert "sk-secret" not in stored[0] and stored[1] == "9999" and decrypt_secret(stored[0]) == "sk-secret-ZZZZ9999"


# ---------------------------------------------------------------- kill switch, missing / disabled routes, degradation
async def test_kill_switch_and_disabled_task_and_no_route(rec):
    await build(steps=[{"model": "mock-primary"}])
    await set_setting("ai_kill_switch", True)
    with pytest.raises(AIUnavailable) as e:
        await run("intent_classify", MSG, now=NOW)
    assert e.value.reason == "KILL_SWITCH" and not rec.calls
    await set_setting("ai_kill_switch", False)
    assert (await run("intent_classify", MSG, now=NOW)).fallback_depth == 0
    with pytest.raises(AIUnavailable) as e2:
        await run("translate", MSG, now=NOW)  # no route configured at all
    assert e2.value.reason == "NO_ROUTE"
    await build(task="summarise", steps=[{"model": "mock-primary", "provider": "p-off"}], enabled=False)
    with pytest.raises(AIUnavailable) as e3:
        await run("summarise", MSG, now=NOW)
    assert e3.value.reason == "TASK_DISABLED"
    reasons = {r.error_code for r in await logs("summarise")} | {r.error_code for r in await logs("translate")} | {r.error_code for r in await logs()}
    assert {"KILL_SWITCH", "NO_ROUTE", "TASK_DISABLED"} <= reasons


async def test_empty_seeded_route_degrades_gracefully(rec):
    await build(steps=[])  # the shipped state: a route per task with no steps
    assert await run_or_none("intent_classify", MSG, now=NOW) is None
    with pytest.raises(AIUnavailable) as e:
        await run("intent_classify", MSG, now=NOW)
    assert e.value.reason == "ALL_STEPS_FAILED" and not rec.calls


async def test_scheduling_still_works_with_ai_switched_off(client, world):
    await set_setting("ai_kill_switch", True)
    await login(client, "coordinator")
    r = await client.post("/api/v1/scheduling/options", json={"shipment_id": str(world.shipment_a.id)})
    assert r.status_code == 200  # nothing in scheduling or booking depends on AI
    with pytest.raises(AIUnavailable):
        await run("intent_classify", MSG, now=NOW)


# ---------------------------------------------------------------- fallback on every failure class
@pytest.mark.parametrize("bad,code", [("mock-timeout", "timeout"), ("mock-429", "rate_limit"), ("mock-500", "server_error"),
                                      ("mock-network", "network"), ("mock-refusal", "refusal")])
async def test_fallback_on_provider_errors(rec, bad, code):
    await build(steps=[{"model": bad}, {"model": "mock-primary"}])
    res = await run("intent_classify", MSG, now=NOW)
    assert res.fallback_depth == 1 and res.model == "mock-primary" and res.provider == "mock2"
    assert res.path[0]["outcome"] == f"error:{code}" and res.path[1]["outcome"] == "ok"
    [row] = await logs()
    assert row.status == "ok" and row.fallback_depth == 1 and row.error_code == code


async def test_refusal_without_fallback_permission_stops(rec):
    await build(steps=[{"model": "mock-refusal"}, {"model": "mock-primary"}], fallback_on_refusal=False)
    with pytest.raises(AIUnavailable) as e:
        await run("intent_classify", MSG, now=NOW)
    assert e.value.reason == "REFUSAL"


async def test_retries_only_transient_errors(rec):
    await build(steps=[{"model": "mock-500", "retries": 2}, {"model": "mock-primary"}])
    await run("intent_classify", MSG, now=NOW)
    assert [c.model_name for c in rec.calls] == ["mock-500"] * 3 + ["mock-primary"]
    rec.calls.clear()
    await build(task="translate", steps=[{"model": "mock-429", "retries": 3, "provider": "q"}, {"model": "mock-primary", "provider": "q2"}])
    await run("translate", MSG, now=NOW)
    assert [c.model_name for c in rec.calls] == ["mock-429", "mock-primary"]  # 429 is not retried on the same key


async def test_all_steps_fail_raises_and_logs_full_path(rec):
    await build(steps=[{"model": "mock-500"}, {"model": "mock-timeout"}, {"model": "mock-network"}])
    with pytest.raises(AIUnavailable) as e:
        await run("intent_classify", MSG, now=NOW)
    assert [p["outcome"] for p in e.value.path] == ["error:server_error", "error:timeout", "error:network"]
    [row] = await logs()
    assert row.status == "failed" and row.error_code == "ALL_STEPS_FAILED" and row.fallback_depth == 2 and len(row.path) == 3
    assert await run_or_none("intent_classify", MSG, now=NOW) is None


# ---------------------------------------------------------------- structured output: invalid JSON and repair
async def test_invalid_json_is_repaired_once_then_falls_back(rec):
    await build(steps=[{"model": "mock-badjson-once"}])
    res = await run("intent_classify", MSG, response_schema=Intent, now=NOW)
    assert res.parsed.intent == "report_delay" and res.path[0].get("repaired") is True and res.fallback_depth == 0
    assert len(rec.calls) == 2 and "Return only valid JSON" in str(rec.calls[1].messages[-1])
    rec.calls.clear()
    await build(task="summarise", steps=[{"model": "mock-badjson", "provider": "b1"}, {"model": "mock-primary", "provider": "b2"}])
    res2 = await run("summarise", MSG, response_schema=Intent, now=NOW)
    assert res2.fallback_depth == 1 and res2.path[0]["outcome"] == "error:invalid_output" and res2.parsed.intent == "report_delay"


async def test_json_in_code_fences_is_accepted():
    from app.modules.ai.router import _extract_json, _parse

    assert _extract_json('```json\n{"intent": "unknown"}\n```') == {"intent": "unknown"}
    assert _parse('noise {"intent":"unknown","delay_minutes":5}', Intent).delay_minutes == 5
    assert _parse("plain", None) is None


# ---------------------------------------------------------------- auth failure disables the key
async def test_auth_error_disables_key_alerts_admins_and_falls_back(rec):
    ids = await build(steps=[{"model": "mock-auth", "keys": ["sk-badbadbad-0001"]}, {"model": "mock-primary"}])
    res = await run("intent_classify", MSG, now=NOW)
    assert res.fallback_depth == 1
    async with async_session_factory() as db:
        k = await db.get(AIProviderKey, ids["keys"][0])
        assert k.status == "failed" and "authentication" in k.last_error
    ev = await outbox("ai.key_disabled")
    assert len(ev) == 1 and "sk-badbadbad" not in str(ev[0].payload)
    again = await run("intent_classify", MSG, now=NOW)
    assert again.path[0]["outcome"] == "skipped:no_healthy_key" and again.fallback_depth == 1


# ---------------------------------------------------------------- budgets
async def test_budget_exhaustion_skips_step_and_alerts_once(rec):
    ids = await build(steps=[{"model": "mock-primary", "in_price": 100000, "out_price": 100000}, {"model": "mock-fast"}])
    async with async_session_factory() as db:
        db.add(AIBudget(scope="provider", scope_id="mock1", period="monthly", limit_amount=Decimal("2.0"), alert_threshold=0.5))
        await db.commit()
    first = await run("intent_classify", MSG, now=NOW)
    assert first.fallback_depth == 0 and first.cost > 0
    alerts = await outbox("ai.budget_threshold")
    assert len(alerts) == 1 and alerts[0].payload["scope"] == "provider"
    second = await run("intent_classify", MSG, now=NOW)  # budget now exhausted: primary skipped
    assert second.path[0]["outcome"] == "skipped:budget_exhausted" and second.fallback_depth == 1 and second.model == "mock-fast"
    assert len(await outbox("ai.budget_threshold")) == 1  # one alert per period, not per call
    _ = ids


async def test_task_global_and_key_budgets(rec):
    await build(steps=[{"model": "mock-primary", "in_price": 1000000, "out_price": 1000000, "keys": ["sk-budget-0001"], "key_budget": "0.0001"}])
    await run("intent_classify", MSG, now=NOW)
    with pytest.raises(AIUnavailable) as e:
        await run("intent_classify", MSG, now=NOW)
    assert e.value.path[0]["outcome"] == "skipped:budget_exhausted"
    async with async_session_factory() as db:
        db.add(AIBudget(scope="global", period="daily", limit_amount=Decimal("0.0000001")))
        await db.commit()
    await build(task="translate", steps=[{"model": "mock-primary", "provider": "g1", "in_price": 1000000}])
    with pytest.raises(AIUnavailable) as e2:
        await run("translate", MSG, now=NOW)  # global daily budget already spent by the earlier call
    assert e2.value.path[0]["outcome"] == "skipped:budget_exhausted"


# ---------------------------------------------------------------- circuit breaker
async def test_breaker_unit_closed_open_half_open_cycle():
    cfg = breaker.BreakerConfig(threshold=3, window_seconds=60, cooldown_seconds=30)
    r = get_redis()
    try:
        t = NOW.timestamp()
        assert await breaker.allow(r, "provider", "p1", cfg, t)
        assert [await breaker.failure(r, "provider", "p1", cfg, t) for _ in range(3)] == [False, False, True]
        assert await breaker.state(r, "provider", "p1", cfg, t + 1) == "open" and not await breaker.allow(r, "provider", "p1", cfg, t + 1)
        assert await breaker.state(r, "provider", "p1", cfg, t + 31) == "half_open"
        assert await breaker.allow(r, "provider", "p1", cfg, t + 31) is True       # the single probe
        assert await breaker.allow(r, "provider", "p1", cfg, t + 31) is False      # everyone else waits
        assert await breaker.failure(r, "provider", "p1", cfg, t + 31) is True      # probe failed: re-open
        assert await breaker.state(r, "provider", "p1", cfg, t + 40) == "open"
        assert await breaker.allow(r, "provider", "p1", cfg, t + 62) is True        # next probe
        await breaker.success(r, "provider", "p1")
        assert await breaker.state(r, "provider", "p1", cfg, t + 62) == "closed" and await breaker.allow(r, "provider", "p1", cfg, t + 63)
        assert breaker.BreakerConfig.from_setting({"threshold": "7"}).threshold == 7
        assert breaker.BreakerConfig.from_setting(None).cooldown_seconds == 30
    finally:
        await r.aclose()


async def test_breaker_opens_in_router_skips_provider_then_recovers(rec):
    await set_setting("ai_breaker", {"threshold": 3, "window_seconds": 60, "cooldown_seconds": 30})
    ids = await build(steps=[{"model": "mock-500"}, {"model": "mock-primary"}])
    for _ in range(3):
        await run("intent_classify", MSG, now=NOW)
    assert len(await outbox("ai.provider_failure")) == 1
    rec.calls.clear()
    res = await run("intent_classify", MSG, now=NOW + timedelta(seconds=5))
    assert res.path[0]["outcome"] == "skipped:circuit_open" and [c.model_name for c in rec.calls] == ["mock-primary"]
    # cooldown over: one probe goes to the failing provider (still down -> re-opens), then fallback succeeds
    rec.calls.clear()
    res2 = await run("intent_classify", MSG, now=NOW + timedelta(seconds=40))
    assert [c.model_name for c in rec.calls][:1] == ["mock-500"] and res2.fallback_depth == 1
    # provider is fixed: swap the model to a healthy one, probe succeeds and the breaker closes
    async with async_session_factory() as db:
        m = await db.get(AIModel, ids["models"][0])
        m.model_name = "mock-primary"
        await db.commit()
    res3 = await run("intent_classify", MSG, now=NOW + timedelta(seconds=100))
    assert res3.fallback_depth == 0 and res3.path[0]["outcome"] == "ok"
    res4 = await run("intent_classify", MSG, now=NOW + timedelta(seconds=101))
    assert res4.fallback_depth == 0


# ---------------------------------------------------------------- key pools
async def test_round_robin_cycles_keys(rec):
    await build(steps=[{"model": "mock-primary", "keys": ["sk-aaaa-0001", "sk-bbbb-0002", "sk-cccc-0003"], "strategy": "round_robin"}])
    for _ in range(6):
        await run("intent_classify", MSG, now=NOW)
    used = [c.api_key for c in rec.calls]
    assert used == ["sk-aaaa-0001", "sk-bbbb-0002", "sk-cccc-0003"] * 2


async def test_weighted_and_single_strategies(rec, monkeypatch):
    await build(steps=[{"model": "mock-primary", "keys": ["sk-heavy-0001", "sk-light-0002"], "strategy": "weighted", "weights": [1000, 1]}])
    for _ in range(30):
        await run("intent_classify", MSG, now=NOW)
    heavy = sum(1 for c in rec.calls if c.api_key == "sk-heavy-0001")
    assert heavy >= 27
    rec.calls.clear()
    await build(task="translate", steps=[{"model": "mock-primary", "provider": "s1", "keys": ["sk-one-0001", "sk-two-0002"], "strategy": "single"}])
    for _ in range(3):
        await run("translate", MSG, now=NOW)
    assert {c.api_key for c in rec.calls} == {"sk-one-0001"}


async def test_rate_limited_key_rotates_to_next_key_in_pool(rec):
    await build(steps=[{"model": "mock-primary", "keys": ["sk-limited-0001", "sk-spare-0002"], "strategy": "single"}, {"model": "mock-fast"}])
    rec.fail_for_key["sk-limited-0001"] = "rate_limit"
    res = await run("intent_classify", MSG, now=NOW)
    assert res.fallback_depth == 0 and [c.api_key for c in rec.calls] == ["sk-limited-0001", "sk-spare-0002"]


async def test_failed_or_disabled_keys_are_never_used(rec):
    ids = await build(steps=[{"model": "mock-primary", "keys": ["sk-dead-0001", "sk-live-0002"], "strategy": "round_robin"}])
    async with async_session_factory() as db:
        (await db.get(AIProviderKey, ids["keys"][0])).status = "disabled"
        await db.commit()
    for _ in range(3):
        await run("intent_classify", MSG, now=NOW)
    assert {c.api_key for c in rec.calls} == {"sk-live-0002"}


# ---------------------------------------------------------------- conditions, local rate limit, simulated failure
async def test_step_conditions_by_language_and_length(rec):
    await build(steps=[{"model": "mock-primary", "conditions": {"languages": ["hi"]}},
                       {"model": "mock-fast", "conditions": {"max_input_chars": 20}},
                       {"model": "mock-weak"}])
    hi = await run("intent_classify", MSG, context={"language": "hi"}, now=NOW)
    assert hi.model == "mock-primary"
    en = await run("intent_classify", MSG, context={"language": "en"}, now=NOW)
    assert [p["outcome"] for p in en.path] == ["skipped:condition", "skipped:condition", "ok"] and en.model == "mock-weak"
    short = await run("intent_classify", [{"role": "user", "content": "late"}], context={"language": "en"}, now=NOW)
    assert short.model == "mock-fast" and short.fallback_depth == 1


async def test_local_provider_rpm_limit_skips_step(rec):
    await build(steps=[{"model": "mock-primary", "rpm": 2}, {"model": "mock-fast"}])
    out = [await run("intent_classify", MSG, now=NOW) for _ in range(3)]
    assert [o.fallback_depth for o in out] == [0, 0, 1] and out[2].path[0]["outcome"] == "skipped:rate_limited_locally"


async def test_forced_fault_simulates_provider_failure_and_counts_towards_breaker(rec):
    ids = await build(steps=[{"model": "mock-primary"}, {"model": "mock-fast"}])
    r = get_redis()
    try:
        await r.set(f"ai:fault:{ids['providers'][0]}", "timeout", ex=60)
    finally:
        await r.aclose()
    res = await run("intent_classify", MSG, now=NOW)
    assert res.fallback_depth == 1 and res.path[0]["outcome"] == "error:timeout" and res.path[0]["forced"] is True
    assert all(c.model_name != "mock-primary" for c in rec.calls)


async def test_disabled_provider_or_model_is_skipped(rec):
    ids = await build(steps=[{"model": "mock-primary"}, {"model": "mock-fast"}])
    async with async_session_factory() as db:
        (await db.get(AIProvider, ids["providers"][0])).status = "disabled"
        await db.commit()
    res = await run("intent_classify", MSG, now=NOW)
    assert res.path[0]["outcome"] == "skipped:disabled" and res.model == "mock-fast"


# ---------------------------------------------------------------- privacy
async def test_pii_masked_for_providers_not_allowed_and_restored(rec):
    await build(steps=[{"model": "mock-primary", "allow_pii": False}])
    msgs = [{"role": "system", "content": "Draft a reply."},
            {"role": "user", "content": "Driver Imran Khan on RJ14GT4101, call +919811100001 or 9811100002 about SHP1002"}]
    res = await run("intent_classify", msgs, context={"pii_names": ["Imran Khan"]}, now=NOW)
    sent = str(rec.calls[0].messages)
    for secret in ("Imran", "RJ14GT4101", "9811100001", "9811100002"):
        assert secret not in sent
    assert "[[NAME_1]]" in sent and "[[VEHICLE_1]]" in sent and "[[PHONE_1]]" in sent
    assert "SHP1002" in sent  # shipment codes are not personal data
    assert "Imran Khan" in res.text or "[[" not in res.text  # placeholders restored in the answer


async def test_pii_not_masked_when_provider_allowed(rec):
    await build(steps=[{"model": "mock-primary", "allow_pii": True}])
    await run("intent_classify", [{"role": "user", "content": "call +919811100001"}], now=NOW)
    assert "+919811100001" in str(rec.calls[0].messages)


def test_masker_round_trip_and_reuse():
    m = Masker(["Asha Verma"])
    out = m.mask("Asha Verma (+91 98111 00001) drives MH12AB1234; asha verma again, same +91 98111 00001")
    assert out.count("[[NAME_1]]") == 2 and out.count("[[PHONE_1]]") == 2 and "[[VEHICLE_1]]" in out and "[[PHONE_2]]" not in out
    assert m.unmask(out).startswith("Asha Verma (+91 98111 00001) drives MH12AB1234")


async def test_log_bodies_are_stored_redacted_only_when_enabled(rec):
    await build(steps=[{"model": "mock-primary"}])
    await run("intent_classify", [{"role": "user", "content": "my number 9811100001 RJ14GT4101"}], now=NOW)
    assert (await logs())[0].prompt_redacted is None
    await set_setting("ai_log_bodies", True)
    await run("intent_classify", [{"role": "user", "content": "my number 9811100001 RJ14GT4101"}], now=NOW)
    body = (await logs())[1]
    assert "9811100001" not in body.prompt_redacted and "RJ14GT4101" not in body.prompt_redacted and "[phone]" in body.prompt_redacted
    assert body.response_redacted


# ---------------------------------------------------------------- mock classifier (drives the simulator and evaluations)
@pytest.mark.parametrize("text_,intent,delay", [
    ("Truck breakdown, 2 hours late", "report_delay", 120), ("गाड़ी 3 घंटे लेट है", "report_delay", 180),
    ("Traffic jam, 45 minutes delay", "report_delay", 45), ("what slots are available after 4 pm", "ask_options", None),
    ("accident ho gaya", "safety_issue", None), ("I reached the gate", "report_arrival", None),
    ("kab hai meri booking", "ask_status", None), ("haan theek hai", "accept_suggestion", None), ("nahi", "decline_suggestion", None),
    ("hello", "unknown", None)])
def test_mock_classifier(text_, intent, delay):
    out = classify(text_)
    assert out["intent"] == intent and out["delay_minutes"] == delay


def test_weak_mock_model_is_english_only():
    assert classify("गाड़ी 3 घंटे लेट है", english_only=True)["intent"] == "unknown"
    assert classify("Truck breakdown, 2 hours late", english_only=True)["intent"] == "report_delay"


async def test_mock_client_returns_response_object():
    r = await MockClient().complete(__import__("app.modules.ai.clients.base", fromlist=["CallRequest"]).CallRequest(
        kind="mock", base_url=None, model_name="mock-primary", api_key=None, messages=MSG, json_mode=False))
    assert isinstance(r, CallResponse) and r.tokens_in > 0


# ---------------------------------------------------------------- architecture rule: provider SDKs only inside modules/ai
def test_no_provider_sdk_imported_outside_modules_ai():
    root = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"^\s*(?:from|import)\s+(litellm|openai|anthropic|google\.generativeai|google\.genai|cohere|mistralai)\b", re.M)
    offenders = []
    for f in root.rglob("*.py"):
        if "modules/ai/" in f.as_posix():
            continue
        if pattern.search(f.read_text(encoding="utf-8")):
            offenders.append(f.relative_to(root).as_posix())
    assert offenders == [], f"Provider SDKs must only be imported inside app/modules/ai: {offenders}"


def test_provider_sdk_import_is_confined_to_one_client_file():
    root = Path(__file__).resolve().parents[1] / "app" / "modules" / "ai"
    files = [f.name for f in root.rglob("*.py") if re.search(r"^\s*(?:from|import)\s+litellm\b", f.read_text(encoding="utf-8"), re.M)
             or re.search(r"^\s+import litellm", f.read_text(encoding="utf-8"), re.M)]
    assert files == ["litellm_client.py"]


_ = uuid
