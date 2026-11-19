"""AI narratives for the analytics views. The model only EXPLAINS numbers that code has already computed: it receives
aggregated, de-identified figures (no names, phone numbers, shipment codes), returns prose, and nothing it says is stored or
acted on. If AI is off or unavailable the caller still gets the numbers and an `ai_available: false` flag."""
import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

from app.core.idempotency import get_redis
from app.modules.ai.router import run_or_none

CACHE_TTL_S = 600
TASK_FOR_VIEW = {"network": "dock_insight", "facility": "dock_insight", "carrier": "driver_insight", "coordinator": "summarise"}
LANGUAGES = {"en": "English", "hi": "Hindi"}

SYSTEM = (
    "You write a short operations briefing for a logistics dock-scheduling platform. You are given JSON with aggregated figures for "
    "one period. Rules: use ONLY numbers present in the JSON; never invent a figure, a name or a cause; write 3 to 5 short bullet "
    "points, each one finding with its number and what changed against the previous period; say plainly when data is too thin to "
    "conclude; do not recommend changing any booking or slot, because people decide that; no greetings. Write in {language}."
)


def facts_for(view: str, result: dict[str, Any]) -> dict[str, Any]:
    """Only aggregates. Driver and lane names are replaced by ranks so nothing identifying leaves the platform."""
    facts: dict[str, Any] = {
        "view": view, "period": result["period"]["range"], "bucket": result["period"]["bucket"],
        "kpis": {k: {"value": v["value"], "previous": v["previous"], "change_pct": v["change"]} for k, v in result["kpis"].items()},
    }
    t = result["tables"]
    for name in ("delay_causes", "escalation_reasons", "request_mix"):
        if name in t:
            facts[name] = [{"key": r["key"], "count": r["count"], "share_pct": r["share"]} for r in t[name][:6]]
    if "by_dock" in t:
        facts["docks_by_utilisation"] = [{"rank": i + 1, "type": r["type"], "utilisation_pct": r["utilisation_pct"]} for i, r in enumerate(sorted(t["by_dock"], key=lambda r: -r["utilisation_pct"])[:8])]
    if "heatmap" in t and t["heatmap"]:
        top = sorted(t["heatmap"], key=lambda r: -r["utilisation_pct"])[:3]
        facts["busiest_hours"] = [{"weekday": r["dow"], "hour": r["hour"], "utilisation_pct": r["utilisation_pct"]} for r in top]
    if "by_driver" in t:
        facts["drivers_by_late_rate"] = [{"rank": i + 1, "trips": r["trips"], "late_rate_pct": r["late_rate"]} for i, r in enumerate(t["by_driver"][:5])]
    if "by_lane" in t:
        facts["lanes_by_late_rate"] = [{"rank": i + 1, "trips": r["trips"], "late_rate_pct": r["late_rate"], "avg_wait_min": r["avg_wait_min"]} for i, r in enumerate(t["by_lane"][:5])]
    return facts


def _digest(view: str, scope_key: str, period: dict, language: str) -> str:
    bucket = int(time.time() // CACHE_TTL_S)
    window = f"{period['from']}|{period['to']}" if period["range"] == "custom" else period["range"]
    return hashlib.sha256(f"{view}|{scope_key}|{window}|{language}|{bucket}".encode()).hexdigest()[:24]


async def narrative(view: str, result: dict[str, Any], *, scope_key: str, language: str = "en") -> dict[str, Any]:
    task = TASK_FOR_VIEW[view]
    lang = language if language in LANGUAGES else "en"
    key = f"insight:{task}:{_digest(view, scope_key, result['period'], lang)}"
    redis = get_redis()
    try:
        try:
            cached = await redis.get(key)
        except Exception:
            cached = None
        if cached:
            return {**json.loads(cached), "cached": True}
        facts = facts_for(view, result)
        messages = [{"role": "system", "content": SYSTEM.format(language=LANGUAGES[lang])},
                    {"role": "user", "content": "<figures>\n" + json.dumps(facts, default=str, ensure_ascii=False) + "\n</figures>"}]
        res = await run_or_none(task, messages, context={"language": lang})
        out = {"task": task, "ai_available": res is not None and bool((res.text or "").strip()), "text": (res.text.strip() if res and res.text else None),
               "model": res.model if res else None, "generated_at": datetime.now(UTC).isoformat(), "language": lang}
        if out["ai_available"]:
            try:
                await redis.set(key, json.dumps(out), ex=CACHE_TTL_S)
            except Exception:
                pass
        return {**out, "cached": False}
    finally:
        await redis.aclose()
