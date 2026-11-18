"""Where AI is used in the platform: the reviewed catalogue of AI touch points, joined with live usage for each task.
`wired` = code calls it today; `planned` = the task and route exist but no feature calls it yet."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

GUARDS = [
    "AI never writes to the database; it only returns text or a typed result that code validates.",
    "AI never decides capacity: only the scheduling and booking services create, change or release a slot.",
    "Every call goes through one router (ai.run): fallback chain, circuit breakers, budgets, PII masking, kill switch, full log.",
    "If AI is off or unavailable, every feature has a deterministic fallback; nothing fails.",
    "Driver text is passed as delimited data and is never trusted as an instruction.",
]

CATALOGUE = [
    {"task": "intent_classify", "status": "wired", "title": "Understand a driver's WhatsApp message", "portal": "WhatsApp driver assistant",
     "where": "Agent graph, classify_intent step (backend/app/modules/agent/graph.py)",
     "trigger": "A driver sends free text that is not a button tap, a safety/dispute/injection phrase, or an answer to a question the bot just asked.",
     "input": "The driver's message (names and numbers masked unless the provider is allowed PII) plus the language.",
     "output": "Intent (report delay, ask options, arrival, status, ...) and facts: delay minutes, ETA time, cause, latest finish.",
     "affects": "Which question the bot asks next. Facts are re-checked by deterministic parsers before they are stored.",
     "cannot": "Cannot reserve, confirm or release a slot. Cannot write a reply: all reply text comes from the reviewed catalogue.",
     "fallback": "Deterministic parsing plus fixed menus and buttons; two misses escalate to a coordinator."},
    {"task": "driver_chat", "status": "reserved", "title": "Free-form driver replies", "portal": "WhatsApp driver assistant",
     "where": "Route exists; deliberately not called",
     "trigger": "None. Reply text comes from the reviewed catalogue (English, Hindi, Telugu) so nothing the bot says about times or docks can be invented.",
     "input": "-", "output": "-", "affects": "-", "cannot": "-", "fallback": "Not applicable."},
    {"task": "translate", "status": "planned", "title": "Translate coordinator messages to the driver's language", "portal": "Coordinator",
     "where": "Coordinator request detail and conversation reply",
     "trigger": "A coordinator writes a message for a driver whose language differs.", "input": "Coordinator text", "output": "Translated text shown for review before sending",
     "affects": "Wording only", "cannot": "Cannot change slot data", "fallback": "Send the original text or a template."},
    {"task": "summarise", "status": "wired", "title": "Brief the operations desk", "portal": "Coordinator insights",
     "where": "Coordinator, Insights page (backend/app/modules/insights/service.py)",
     "trigger": "A coordinator or admin opens the Insights page; the briefing is cached for 10 minutes per view and period.",
     "input": "Aggregated figures only (request, escalation and bot-resolution counts and rates against the previous period). No names, phone numbers or shipment codes.",
     "output": "Three to five short bullets explaining the figures.", "affects": "Reading only. Nothing the model writes is stored or acted on.",
     "cannot": "Cannot change a request, hold or booking, and cannot recommend one: people decide.", "fallback": "The numbers and charts are shown with an 'AI unavailable' notice."},
    {"task": "coordinator_suggestion", "status": "planned", "title": "Explain the recommended decision", "portal": "Coordinator",
     "where": "Request detail, recommendation panel", "trigger": "A coordinator opens a request.",
     "input": "Engine's ranked options and reasons", "output": "Plain-language explanation", "affects": "Explanation only",
     "cannot": "The rule-based recommendation stays authoritative; AI cannot change the ranking", "fallback": "Show the rule-based reasons."},
    {"task": "driver_insight", "status": "wired", "title": "Explain carrier and driver punctuality", "portal": "Carrier insights",
     "where": "Carrier, Insights page (backend/app/modules/insights/service.py)",
     "trigger": "A carrier user opens Insights; cached for 10 minutes per period.",
     "input": "Aggregated figures only: on-time rate, delay reports, slot moves and decline rate against the previous period, plus drivers and lanes as ranks (no names).",
     "output": "Three to five short bullets explaining the figures.", "affects": "Reading only.",
     "cannot": "Cannot rank, score or penalise a named driver, and cannot change any booking.", "fallback": "The numbers and charts are shown with an 'AI unavailable' notice."},
    {"task": "dock_insight", "status": "wired", "title": "Explain dock utilisation and flow", "portal": "Admin dashboard and Facility reports",
     "where": "Admin dashboard and Facility, Reports (backend/app/modules/insights/service.py)",
     "trigger": "An admin or planner opens the dashboard or reports; cached for 10 minutes per scope and period.",
     "input": "Aggregated figures only: utilisation, on-time rate, wait and dwell, no-shows, delay causes, busiest hours, docks as ranks (no names).",
     "output": "Three to five short bullets explaining the figures.", "affects": "Reading only.",
     "cannot": "Cannot change docks, slots, rules or bookings.", "fallback": "The numbers and charts are shown with an 'AI unavailable' notice."},
    {"task": "transcribe", "status": "planned", "title": "Transcribe driver voice notes", "portal": "WhatsApp driver assistant",
     "where": "Inbound media handling", "trigger": "A driver sends a voice note.", "input": "Audio", "output": "Text fed to the same intent step",
     "affects": "Input only", "cannot": "Same limits as typed text", "fallback": "Ask the driver to type or use the buttons."},
]

ADMIN_TOOLS = [
    {"name": "Playground", "where": "AI management, Overview", "note": "Sends a test message through any task route. Logged like any other call."},
    {"name": "Prompt test", "where": "AI management, Prompts", "note": "Runs a draft prompt against a sample before it is activated."},
    {"name": "Evaluations", "where": "AI management, Evaluations", "note": "Runs the golden set against a model and scores it. Logged as intent_classify calls."},
    {"name": "Simulate failure", "where": "AI management, Routes", "note": "Forces the primary provider to fail to prove the fallback works."},
]


async def build(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=30)
    rows = (await db.execute(text(
        "SELECT task, count(*) AS requests, coalesce(sum(cost), 0) AS cost, coalesce(avg(latency_ms), 0) AS avg_ms, max(created_at) AS last_used, "
        "coalesce(avg((status <> 'ok')::int), 0) AS error_rate, coalesce(sum((status = 'ok' AND fallback_depth > 0)::int), 0) AS fallbacks "
        "FROM ai_usage_logs WHERE created_at >= :s GROUP BY task"), {"s": since})).all()
    live = {r.task: r for r in rows}
    routes = {r[0]: r for r in (await db.execute(text(
        "SELECT r.task, r.enabled, (SELECT count(*) FROM ai_route_steps s WHERE s.route_id = r.id) AS steps FROM ai_routes r"))).all()}
    items = []
    for c in CATALOGUE:
        r, ro = live.get(c["task"]), routes.get(c["task"])
        items.append({**c, "route_enabled": bool(ro.enabled) if ro else False, "route_steps": int(ro.steps) if ro else 0,
                      "last_30d": {"requests": int(r.requests), "cost": str(r.cost), "avg_ms": round(float(r.avg_ms)), "error_rate": round(float(r.error_rate), 4),
                                   "fallbacks": int(r.fallbacks), "last_used": r.last_used} if r else {"requests": 0, "cost": "0", "avg_ms": 0, "error_rate": 0.0,
                                                                                                         "fallbacks": 0, "last_used": None}})
    return {"items": items, "guards": GUARDS, "admin_tools": ADMIN_TOOLS,
            "flow": ["Feature calls ai.run(task)", "Kill switch and task route checked", "Step conditions, circuit breaker, rate limit and budget checked",
                     "PII masked, provider called with the next key in the pool", "On failure, next step in the fallback chain",
                     "Typed result validated (one repair attempt)", "Usage, cost, latency and path logged", "Caller falls back to deterministic behaviour if nothing answers"]}
