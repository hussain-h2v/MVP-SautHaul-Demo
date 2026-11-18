"""AI monitoring: spend, tokens, latency and reliability over a chosen period, plus the full trace of one call.
Read side only (ai_usage_logs); all times are bucketed in the display timezone (Asia/Kolkata)."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationAppError
from app.modules.ai.models import AIModel, AIProvider, AIProviderKey, AIUsageLog

TZ = ZoneInfo("Asia/Kolkata")
RANGES = {"1d": 1, "3d": 3, "7d": 7, "3w": 21, "1m": 30}
SORTS = {"created_at": "created_at", "cost": "cost", "latency": "latency_ms", "tokens": "(tokens_in + tokens_out)"}

_AGG = """count(*) AS requests, coalesce(sum((status = 'ok')::int), 0) AS ok, coalesce(sum((status <> 'ok')::int), 0) AS failed,
  coalesce(sum(tokens_in), 0) AS tokens_in, coalesce(sum(tokens_out), 0) AS tokens_out, coalesce(sum(cost), 0) AS cost,
  coalesce(avg(latency_ms), 0) AS avg_ms,
  coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0) AS p50_ms,
  coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) AS p95_ms,
  coalesce(percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms), 0) AS p99_ms,
  coalesce(max(latency_ms), 0) AS max_ms,
  coalesce(avg((status <> 'ok')::int), 0) AS error_rate,
  coalesce(sum((status = 'ok' AND fallback_depth > 0)::int)::float / nullif(sum((status = 'ok')::int), 0), 0) AS fallback_rate"""


def _row(r) -> dict:
    req = int(r.requests)
    cost = Decimal(r.cost)
    return {"requests": req, "ok": int(r.ok), "failed": int(r.failed), "tokens_in": int(r.tokens_in), "tokens_out": int(r.tokens_out),
            "cost": str(cost), "avg_cost": str(cost / req) if req else "0", "avg_ms": round(float(r.avg_ms)), "p50_ms": round(float(r.p50_ms)),
            "p95_ms": round(float(r.p95_ms)), "p99_ms": round(float(r.p99_ms)), "max_ms": int(r.max_ms),
            "error_rate": round(float(r.error_rate), 4), "fallback_rate": round(float(r.fallback_rate), 4)}


def _window(range_: str, date_from: datetime | None, date_to: datetime | None, now: datetime) -> tuple[datetime, datetime]:
    if range_ == "custom":
        if date_from is None:
            raise ValidationAppError("A custom range needs date_from")
        return date_from, date_to or now + timedelta(minutes=1)
    if range_ not in RANGES:
        raise ValidationAppError("range must be one of " + ", ".join([*RANGES, "custom"]))
    # "1 day" means the last 24 hours; longer ranges end now and start at the local midnight N-1 days ago so days are whole
    if range_ == "1d":
        return now - timedelta(days=1), now + timedelta(minutes=1)
    local = now.astimezone(TZ)
    start = (local - timedelta(days=RANGES[range_] - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), now + timedelta(minutes=1)


def _filters(task, provider, model, status, key_id=None) -> tuple[str, dict]:
    parts, params = [], {}
    for col, name, val in (("task", "task", task), ("provider", "provider", provider), ("model", "model", model), ("status", "status", status)):
        if val:
            parts.append(f"{col} = :{name}")
            params[name] = val
    if key_id:
        parts.append("key_id = :key_id")
        params["key_id"] = key_id
    return ("".join(f" AND {p}" for p in parts)), params


async def overview(db: AsyncSession, *, range_: str = "7d", date_from: datetime | None = None, date_to: datetime | None = None,
                   task: str | None = None, provider: str | None = None, model: str | None = None, status: str | None = None,
                   now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    start, end = _window(range_, date_from, date_to, now)
    extra, fp = _filters(task, provider, model, status)
    params = {"f": start, "t": end, **fp}
    base = f"FROM ai_usage_logs WHERE created_at >= :f AND created_at < :t{extra}"
    totals = (await db.execute(text(f"SELECT {_AGG} {base}"), params)).one()

    span = end - start
    prev = (await db.execute(text(f"SELECT {_AGG} FROM ai_usage_logs WHERE created_at >= :pf AND created_at < :f{extra}"),
                             {"pf": start - span, **params})).one()

    hourly = span <= timedelta(days=3, hours=1)
    unit = "hour" if hourly else "day"
    fmt = "YYYY-MM-DD HH24:00" if hourly else "YYYY-MM-DD"
    series_rows = (await db.execute(text(
        f"SELECT to_char(date_trunc('{unit}', created_at AT TIME ZONE 'Asia/Kolkata'), '{fmt}') AS bucket, {_AGG} {base} GROUP BY 1 ORDER BY 1"), params)).all()
    have = {r.bucket: r for r in series_rows}
    series = []
    cursor = start.astimezone(TZ).replace(minute=0, second=0, microsecond=0) if hourly else start.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    last = end.astimezone(TZ)
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    while cursor <= last and len(series) < 800:
        label = cursor.strftime("%Y-%m-%d %H:00" if hourly else "%Y-%m-%d")
        r = have.get(label)
        series.append({"bucket": label, **(_row(r) if r is not None else _empty())})
        cursor += step

    daily_rows = (await db.execute(text(
        f"SELECT to_char(date_trunc('day', created_at AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS bucket, {_AGG} {base} GROUP BY 1 ORDER BY 1 DESC"), params)).all()

    async def breakdown(col: str) -> list[dict]:
        rows = (await db.execute(text(f"SELECT coalesce({col}, '(none)') AS key, {_AGG} {base} GROUP BY 1 ORDER BY sum(cost) DESC, count(*) DESC"), params)).all()
        total_cost = sum(Decimal(r.cost) for r in rows) or Decimal(1)
        return [{"key": r.key, **_row(r), "cost_share": round(float(Decimal(r.cost) / total_cost), 4)} for r in rows]

    # spend cards ignore the period but respect the filters, so "today" is always today
    local_now = now.astimezone(TZ)
    day0 = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    month0 = day0.replace(day=1)

    async def spend(frm: datetime) -> dict:
        r = (await db.execute(text(f"SELECT coalesce(sum(cost), 0) AS cost, count(*) AS requests FROM ai_usage_logs WHERE created_at >= :f{extra}"),
                              {"f": frm.astimezone(UTC), **fp})).one()
        return {"cost": str(Decimal(r.cost)), "requests": int(r.requests)}

    mtd = await spend(month0)
    days_elapsed = max(1, (day0 - month0).days + 1)
    next_month = (month0 + timedelta(days=32)).replace(day=1)
    days_in_month = (next_month - month0).days
    projected = Decimal(mtd["cost"]) / days_elapsed * days_in_month

    top_cost = (await db.execute(text(f"SELECT id, request_id, task, model, cost, latency_ms, tokens_in, tokens_out, status, created_at {base} ORDER BY cost DESC, created_at DESC LIMIT 5"), params)).all()
    top_slow = (await db.execute(text(f"SELECT id, request_id, task, model, cost, latency_ms, tokens_in, tokens_out, status, created_at {base} ORDER BY latency_ms DESC, created_at DESC LIMIT 5"), params)).all()
    facets = {
        "tasks": [r[0] for r in (await db.execute(text("SELECT DISTINCT task FROM ai_usage_logs ORDER BY 1"))).all()],
        "providers": [r[0] for r in (await db.execute(text("SELECT DISTINCT provider FROM ai_usage_logs WHERE provider IS NOT NULL ORDER BY 1"))).all()],
        "models": [r[0] for r in (await db.execute(text("SELECT DISTINCT model FROM ai_usage_logs WHERE model IS NOT NULL ORDER BY 1"))).all()],
    }

    def call(r) -> dict:
        return {"id": r.id, "request_id": r.request_id, "task": r.task, "model": r.model, "cost": str(r.cost), "latency_ms": r.latency_ms,
                "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "status": r.status, "created_at": r.created_at}

    cur, old = _row(totals), _row(prev)
    return {
        "period": {"range": range_, "from": start, "to": end, "bucket": unit, "timezone": "Asia/Kolkata"},
        "kpis": cur,
        "previous": old,
        "change": {"cost": _pct(cur["cost"], old["cost"]), "requests": _pct(cur["requests"], old["requests"]),
                   "avg_ms": _pct(cur["avg_ms"], old["avg_ms"]), "error_rate": _pct(cur["error_rate"], old["error_rate"])},
        "spend": {"today": await spend(day0), "last_7d": await spend(day0 - timedelta(days=6)), "month_to_date": mtd,
                  "projected_month": str(projected.quantize(Decimal("0.0001"))), "month": month0.strftime("%B %Y")},
        "series": series,
        "daily": [{"bucket": r.bucket, **_row(r)} for r in daily_rows],
        "by_model": await breakdown("model"),
        "by_provider": await breakdown("provider"),
        "by_task": await breakdown("task"),
        "top_cost": [call(r) for r in top_cost],
        "top_slow": [call(r) for r in top_slow],
        "facets": facets,
    }


def _empty() -> dict:
    return {"requests": 0, "ok": 0, "failed": 0, "tokens_in": 0, "tokens_out": 0, "cost": "0", "avg_cost": "0", "avg_ms": 0, "p50_ms": 0,
            "p95_ms": 0, "p99_ms": 0, "max_ms": 0, "error_rate": 0.0, "fallback_rate": 0.0}


def _pct(cur, old) -> float | None:
    a, b = float(cur), float(old)
    return None if b == 0 else round((a - b) / b * 100, 1)


# ---------------------------------------------------------------- logs (filter, sort, paginate)
def _item(r: AIUsageLog) -> dict:
    return {"id": r.id, "request_id": r.request_id, "task": r.task, "provider": r.provider, "model": r.model, "key_id": r.key_id,
            "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "cost": str(r.cost), "latency_ms": r.latency_ms, "status": r.status,
            "fallback_depth": r.fallback_depth, "error_code": r.error_code, "trace_id": r.trace_id, "path": r.path, "created_at": r.created_at}


async def logs(db: AsyncSession, *, range_: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
               request_id: str | None = None, trace_id: str | None = None, task: str | None = None, status: str | None = None,
               provider: str | None = None, model: str | None = None, fallback_only: bool = False, min_latency_ms: int | None = None,
               min_cost: Decimal | None = None, sort: str = "created_at", direction: str = "desc", limit: int = 25, offset: int = 0,
               now: datetime | None = None) -> dict:
    if sort not in SORTS:
        raise ValidationAppError("sort must be one of " + ", ".join(SORTS))
    if direction not in ("asc", "desc"):
        raise ValidationAppError("direction must be asc or desc")
    now = now or datetime.now(UTC)
    if range_:
        date_from, date_to = _window(range_, date_from, date_to, now)
    where, params = ["true"], {}
    for col, name, val in (("task", "task", task), ("status", "status", status), ("provider", "provider", provider), ("model", "model", model),
                           ("trace_id", "trace_id", trace_id)):
        if val:
            where.append(f"{col} = :{name}")
            params[name] = val
    if request_id:
        where.append("request_id ILIKE :rid")
        params["rid"] = f"%{request_id}%"
    if date_from:
        where.append("created_at >= :f")
        params["f"] = date_from
    if date_to:
        where.append("created_at < :t")
        params["t"] = date_to
    if fallback_only:
        where.append("fallback_depth > 0")
    if min_latency_ms is not None:
        where.append("latency_ms >= :ml")
        params["ml"] = min_latency_ms
    if min_cost is not None:
        where.append("cost >= :mc")
        params["mc"] = min_cost
    clause = " AND ".join(where)
    agg = (await db.execute(text(f"SELECT count(*) AS n, coalesce(sum(cost), 0) AS cost, coalesce(sum(tokens_in), 0) AS tin, coalesce(sum(tokens_out), 0) AS tout FROM ai_usage_logs WHERE {clause}"), params)).one()
    ids = (await db.execute(text(f"SELECT id FROM ai_usage_logs WHERE {clause} ORDER BY {SORTS[sort]} {direction}, id LIMIT :lim OFFSET :off"),
                            {**params, "lim": limit, "off": offset})).scalars().all()
    rows = {r.id: r for r in (await db.execute(select(AIUsageLog).where(AIUsageLog.id.in_(ids)))).scalars().all()} if ids else {}
    return {"total": int(agg.n), "page_cost": str(Decimal(agg.cost)), "page_tokens_in": int(agg.tin), "page_tokens_out": int(agg.tout),
            "items": [_item(rows[i]) for i in ids if i in rows]}


# ---------------------------------------------------------------- one call, in full
def _outcome(o: str | None) -> tuple[str, str | None]:
    if not o:
        return "not_reached", None
    if o == "ok":
        return "success", None
    kind, _, detail = o.partition(":")
    return ("skipped" if kind == "skipped" else "error"), detail or None


async def trace(db: AsyncSession, log_id) -> dict:
    r = await db.get(AIUsageLog, log_id)
    if r is None:
        raise NotFoundError("Log entry not found")
    model = None
    if r.provider and r.model:
        model = (await db.execute(select(AIModel).join(AIProvider, AIProvider.id == AIModel.provider_id)
                                  .where(AIProvider.name == r.provider, AIModel.model_name == r.model))).scalar_one_or_none()
    inp = Decimal(model.input_price) if model else Decimal(0)
    out = Decimal(model.output_price) if model else Decimal(0)
    in_cost, out_cost = inp * r.tokens_in / Decimal(1_000_000), out * r.tokens_out / Decimal(1_000_000)
    key = await db.get(AIProviderKey, r.key_id) if r.key_id else None

    attempts, elapsed = [], 0
    for i, e in enumerate(r.path or [], start=1):
        outcome, detail = _outcome(e.get("outcome"))
        ms = e.get("ms")
        attempts.append({"n": i, "step": e.get("step"), "provider": e.get("provider"), "model": e.get("model"), "outcome": outcome, "detail": detail,
                         "ms": ms, "starts_at_ms": elapsed if ms is not None else None, "key_id": e.get("key_id"), "forced": bool(e.get("forced")),
                         "repaired": bool(e.get("repaired"))})
        if ms:
            elapsed += int(ms)
    same_trace = []
    if r.trace_id:
        same_trace = [{"id": x.id, "task": x.task, "model": x.model, "status": x.status, "cost": str(x.cost), "created_at": x.created_at}
                      for x in (await db.execute(select(AIUsageLog).where(AIUsageLog.trace_id == r.trace_id, AIUsageLog.id != r.id)
                                                 .order_by(AIUsageLog.created_at).limit(20))).scalars().all()]
    return {
        **_item(r), "prompt_redacted": r.prompt_redacted, "response_redacted": r.response_redacted,
        "tokens_total": r.tokens_in + r.tokens_out,
        "pricing": {"currency": "USD", "unit": "per 1M tokens", "input_price": str(inp), "output_price": str(out),
                    "input_cost": str(in_cost.quantize(Decimal("0.000001"))), "output_cost": str(out_cost.quantize(Decimal("0.000001"))),
                    "total_cost": str(r.cost), "priced": model is not None},
        "key": {"id": r.key_id, "label": key.label if key else None, "last4": key.key_last4 if key else None},
        "attempts": attempts, "final_outcome": "answered" if r.status == "ok" else ("blocked" if r.status == "disabled" else "unavailable"),
        "used_fallback": r.fallback_depth > 0, "tokens_per_second": round(r.tokens_out / (r.latency_ms / 1000), 1) if r.latency_ms and r.tokens_out else None,
        "same_trace": same_trace,
        "bodies_stored": bool(r.prompt_redacted or r.response_redacted),
    }
