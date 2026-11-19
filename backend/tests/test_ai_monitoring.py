"""AI monitoring: period windows, hour/day buckets, spend cards, breakdowns, filters, sort + pagination, per-call trace, usage map."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.db import async_session_factory
from app.modules.ai.models import AIModel, AIProvider, AIUsageLog
from tests.conftest import login
from tests.m4_helpers import m4  # noqa: F401

API = "/api/v1/ai"


async def as_admin(client):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    await login(client, "admin")


async def log(*, task="translate", provider="Prov A", model="m-big", status="ok", depth=0, ms=100, cost="0.01", tin=1000, tout=200,
              ago=timedelta(hours=1), path=None, trace_id=None, request_id=None):
    async with async_session_factory() as db:
        row = AIUsageLog(request_id=request_id or uuid.uuid4().hex[:20], task=task, provider=provider, model=model, tokens_in=tin, tokens_out=tout,
                         cost=Decimal(cost), latency_ms=ms, status=status, fallback_depth=depth, path=path or [], trace_id=trace_id,
                         created_at=datetime.now(UTC) - ago)
        db.add(row)
        await db.commit()
        return row.id


async def test_period_windows_and_comparison(client, world):
    await as_admin(client)
    await log(cost="0.10", ago=timedelta(hours=2))               # inside the last 24 hours
    await log(cost="0.20", ago=timedelta(days=2))                # inside 3 days, not 1 day
    await log(cost="0.40", ago=timedelta(days=10))               # inside 3 weeks only
    await log(cost="0.80", ago=timedelta(days=40))               # outside every range
    got = {r: (await client.get(f"{API}/monitoring", params={"range": r})).json() for r in ("1d", "3d", "7d", "3w", "1m")}
    assert Decimal(got["1d"]["kpis"]["cost"]) == Decimal("0.10") and got["1d"]["period"]["bucket"] == "hour"
    assert Decimal(got["3d"]["kpis"]["cost"]) == Decimal("0.30") and got["3d"]["period"]["bucket"] == "hour"
    assert Decimal(got["7d"]["kpis"]["cost"]) == Decimal("0.30") and got["7d"]["period"]["bucket"] == "day"
    assert Decimal(got["3w"]["kpis"]["cost"]) == Decimal("0.70")
    assert Decimal(got["1m"]["kpis"]["cost"]) == Decimal("0.70")
    assert (await client.get(f"{API}/monitoring", params={"range": "year"})).status_code == 422
    assert (await client.get(f"{API}/monitoring", params={"range": "custom"})).status_code == 422
    # the previous period (the 7 days before) holds the 10 day old call: 0.40 against 0.30 now
    assert got["7d"]["change"]["cost"] == round((0.30 - 0.40) / 0.40 * 100, 1)


async def test_series_fills_empty_buckets_and_sums_match(client, world):
    await as_admin(client)
    await log(cost="0.5", ago=timedelta(hours=1))
    await log(cost="0.25", ago=timedelta(hours=5), status="failed", model=None, provider=None, tin=0, tout=0)
    d = (await client.get(f"{API}/monitoring", params={"range": "1d"})).json()
    assert 24 <= len(d["series"]) <= 26  # one entry per hour, including hours with no traffic
    assert sum(s["requests"] for s in d["series"]) == d["kpis"]["requests"] == 2
    assert sum(Decimal(s["cost"]) for s in d["series"]) == Decimal(d["kpis"]["cost"]) == Decimal("0.75")
    assert d["kpis"]["failed"] == 1 and d["kpis"]["error_rate"] == 0.5
    assert sum(r["requests"] for r in d["daily"]) == 2


async def test_breakdowns_shares_filters_and_facets(client, world):
    await as_admin(client)
    await log(task="translate", provider="Prov A", model="m-big", cost="0.30", ms=100)
    await log(task="translate", provider="Prov A", model="m-big", cost="0.30", ms=300)
    await log(task="summarise", provider="Prov B", model="m-small", cost="0.40", ms=50, depth=1)
    d = (await client.get(f"{API}/monitoring", params={"range": "7d"})).json()
    by = {r["key"]: r for r in d["by_model"]}
    assert by["m-big"]["requests"] == 2 and by["m-big"]["cost_share"] == 0.6 and by["m-small"]["cost_share"] == 0.4
    assert {r["key"] for r in d["by_provider"]} == {"Prov A", "Prov B"} and {r["key"] for r in d["by_task"]} == {"translate", "summarise"}
    assert d["facets"] == {"tasks": ["summarise", "translate"], "providers": ["Prov A", "Prov B"], "models": ["m-big", "m-small"]}
    f = (await client.get(f"{API}/monitoring", params={"range": "7d", "model": "m-big"})).json()
    assert f["kpis"]["requests"] == 2 and Decimal(f["kpis"]["cost"]) == Decimal("0.60") and f["kpis"]["avg_ms"] == 200
    assert d["top_cost"][0]["model"] == "m-small" and d["top_slow"][0]["latency_ms"] == 300


async def test_spend_cards_today_month_and_projection(client, world):
    await as_admin(client)
    await log(cost="1.00", ago=timedelta(minutes=5))
    d = (await client.get(f"{API}/monitoring", params={"range": "1d"})).json()
    assert Decimal(d["spend"]["today"]["cost"]) == Decimal("1.00") and d["spend"]["today"]["requests"] == 1
    assert Decimal(d["spend"]["month_to_date"]["cost"]) >= Decimal("1.00") and Decimal(d["spend"]["projected_month"]) >= Decimal(d["spend"]["month_to_date"]["cost"])


async def test_logs_filter_sort_and_paginate(client, world):
    await as_admin(client)
    for i in range(7):
        await log(cost=f"0.0{i + 1}", ms=100 * (i + 1), tin=10 * (i + 1), tout=1)
    await log(status="failed", model=None, provider=None, ms=5000, cost="0", tin=0, tout=0, depth=1, path=[{"step": 1, "outcome": "error:timeout", "ms": 5000}])
    p1 = (await client.get(f"{API}/logs", params={"limit": 3, "offset": 0, "sort": "cost", "direction": "desc"})).json()
    p3 = (await client.get(f"{API}/logs", params={"limit": 3, "offset": 6, "sort": "cost", "direction": "desc"})).json()
    assert p1["total"] == 8 and [Decimal(i["cost"]) for i in p1["items"]] == [Decimal("0.07"), Decimal("0.06"), Decimal("0.05")]
    assert len(p3["items"]) == 2 and p3["items"][-1]["status"] == "failed"
    assert Decimal(p1["page_cost"]) == Decimal("0.28")  # total over the whole filtered set, not just the page
    slow = (await client.get(f"{API}/logs", params={"sort": "latency", "limit": 1})).json()["items"][0]
    assert slow["latency_ms"] == 5000
    assert (await client.get(f"{API}/logs", params={"min_latency_ms": 500})).json()["total"] == 4
    assert (await client.get(f"{API}/logs", params={"min_cost": "0.05"})).json()["total"] == 3
    assert (await client.get(f"{API}/logs", params={"fallback_only": "true"})).json()["total"] == 1
    assert (await client.get(f"{API}/logs", params={"status": "failed"})).json()["total"] == 1
    assert (await client.get(f"{API}/logs", params={"model": "m-big"})).json()["total"] == 7
    assert (await client.get(f"{API}/logs", params={"sort": "nonsense"})).status_code == 422
    assert (await client.get(f"{API}/logs", params={"range": "1d"})).json()["total"] == 8
    assert (await client.get(f"{API}/logs", params={"limit": 500})).status_code == 422


async def test_request_id_search_matches_part_of_the_id(client, world):
    await as_admin(client)
    await log(request_id="abc123needle456")
    await log()
    assert (await client.get(f"{API}/logs", params={"request_id": "needle"})).json()["total"] == 1


async def test_trace_shows_attempts_cost_maths_and_related_calls(client, world):
    await as_admin(client)
    async with async_session_factory() as db:
        p = AIProvider(name="Prov T", kind="mock", status="enabled")
        db.add(p)
        await db.flush()
        db.add(AIModel(provider_id=p.id, model_name="m-t", input_price=Decimal("3"), output_price=Decimal("15"), status="active"))
        await db.commit()
    path = [{"step": 1, "provider": "Prov X", "model": "m-x", "outcome": "error:timeout", "ms": 800},
            {"step": 2, "provider": "Prov T", "model": "m-t", "outcome": "ok", "ms": 400}]
    first = await log(provider="Prov T", model="m-t", tin=2000, tout=500, cost="0.0135", ms=1200, depth=1, path=path, trace_id="trace-1")
    await log(task="summarise", provider="Prov T", model="m-t", trace_id="trace-1")
    t = (await client.get(f"{API}/logs/{first}")).json()
    assert t["tokens_total"] == 2500 and t["final_outcome"] == "answered" and t["used_fallback"] is True
    pr = t["pricing"]
    assert pr["priced"] and Decimal(pr["input_cost"]) == Decimal("0.006") and Decimal(pr["output_cost"]) == Decimal("0.0075")
    assert Decimal(pr["input_cost"]) + Decimal(pr["output_cost"]) == Decimal(pr["total_cost"])
    a = t["attempts"]
    assert [x["outcome"] for x in a] == ["error", "success"] and a[0]["detail"] == "timeout" and a[0]["starts_at_ms"] == 0 and a[1]["starts_at_ms"] == 800
    assert t["tokens_per_second"] == round(500 / 1.2, 1)
    assert len(t["same_trace"]) == 1 and t["same_trace"][0]["task"] == "summarise"
    assert (await client.get(f"{API}/logs/{uuid.uuid4()}")).status_code == 404


async def test_blocked_call_trace_says_blocked(client, world):
    await as_admin(client)
    i = await log(status="disabled", model=None, provider=None, tin=0, tout=0, cost="0", ms=0)
    t = (await client.get(f"{API}/logs/{i}")).json()
    assert t["final_outcome"] == "blocked" and t["attempts"] == [] and t["pricing"]["priced"] is False


async def test_usage_map_lists_wired_and_planned_tasks_with_live_stats(client, world):
    await as_admin(client)
    await log(task="intent_classify", cost="0.02")
    m = (await client.get(f"{API}/usage-map")).json()
    by = {i["task"]: i for i in m["items"]}
    assert by["intent_classify"]["status"] == "wired" and by["intent_classify"]["last_30d"]["requests"] == 1
    assert by["driver_chat"]["status"] == "reserved" and by["translate"]["status"] == "planned" and by["translate"]["last_30d"]["requests"] == 0 and by["summarise"]["status"] == "wired"
    assert m["guards"] and m["flow"] and m["admin_tools"]


async def test_monitoring_is_admin_only(client, world):
    for who in ("facility_planner", "coordinator", "carrier_user"):
        client.cookies.clear()
        client.headers.pop("X-CSRF-Token", None)
        await login(client, who)
        for path in ("/monitoring", "/usage-map", "/logs"):
            assert (await client.get(f"{API}{path}")).status_code == 403, (who, path)


async def test_health_lists_failed_keys_and_step_counts(client, world):
    await as_admin(client)
    h = (await client.get(f"{API}/health")).json()
    assert h["failed_keys"] == [] and all({"steps", "healthy_steps"} <= set(t) for t in h["tasks"])
