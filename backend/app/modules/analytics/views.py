"""Assembles the four analytics views (network, facility, coordinator, carrier): KPIs with a previous-period comparison,
chart series and tables. Pure read; scope comes from analytics.scope."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import Period
from app.modules.analytics import queries
from app.modules.analytics.scope import Scope

VIEWS = ("network", "facility", "coordinator", "carrier")

# Which KPIs each view shows, and whether a rise is good (True), bad (False) or neutral (None). The UI uses this for colour.
KPI_SETS: dict[str, dict[str, bool | None]] = {
    "network": {"utilisation_pct": True, "on_time_rate": True, "avg_wait_min": False, "avg_dwell_min": False, "no_show_rate": False,
               "loads_completed": True, "requests": None, "avg_decision_min": False, "escalations": False, "bot_resolution_rate": True,
               "delay_reports": False},
    "facility": {"utilisation_pct": True, "on_time_rate": True, "avg_wait_min": False, "wait_p90_min": False, "avg_dwell_min": False,
                "loads_completed": True, "no_show_rate": False, "lost_hours": False},
    "coordinator": {"requests": None, "avg_decision_min": False, "decision_p90_min": False, "backlog": False, "escalations": False,
                   "avg_resolution_min": False, "holds_expired": False, "bot_resolution_rate": True},
    "carrier": {"arrivals": None, "on_time_rate": True, "late": False, "delay_reports": False, "avg_declared_delay_min": False,
               "no_show_rate": False, "slot_moves": False, "decline_rate": False},
}

TABLE_COLUMNS: dict[str, list[str]] = {
    "by_dock": ["facility", "dock", "type", "available_min", "booked_min", "utilisation_pct"],
    "heatmap": ["dow", "hour", "available_min", "booked_min", "utilisation_pct"],
    "by_facility": ["facility", "available_min", "booked_min", "utilisation_pct"],
    "dock_events": ["facility", "dock", "type", "events", "hours"],
    "delay_causes": ["key", "count", "share", "avg_delay_min"],
    "escalation_reasons": ["key", "count", "share", "avg_resolution_min"],
    "request_mix": ["key", "count", "share"],
    "by_driver": ["code", "driver", "trips", "late", "late_rate", "avg_late_min", "delay_reports"],
    "by_lane": ["origin", "facility", "trips", "late", "late_rate", "avg_late_min", "avg_wait_min"],
    "series": ["bucket", "arrivals", "late", "loads", "requests", "escalations", "delay_reports", "no_shows", "available_min", "booked_min", "utilisation_pct", "avg_wait_min"],
}
VIEW_TABLES: dict[str, list[str]] = {
    "network": ["series", "by_facility", "delay_causes", "escalation_reasons", "request_mix", "dock_events"],
    "facility": ["series", "by_dock", "heatmap", "dock_events"],
    "coordinator": ["series", "request_mix", "escalation_reasons"],
    "carrier": ["series", "by_driver", "by_lane", "delay_causes"],
}


async def _scalars(db: AsyncSession, sc: Scope, p: Period, now: datetime) -> dict[str, Any]:
    """Every scalar figure for a period; one dict so a view can pick what it needs."""
    u = await queries.utilisation(db, sc, p)
    ev = await queries.dock_events(db, sc, p, now)
    arr = await queries.arrivals(db, sc, p)
    ns = await queries.no_shows(db, sc, p, now)
    rq = await queries.requests(db, sc, p)
    es = await queries.escalations(db, sc, p)
    dl = await queries.delays(db, sc, p)
    bt = await queries.bot(db, sc, p)
    th = await queries.throughput(db, sc, p, now)
    return {
        "utilisation_pct": u["utilisation_pct"], "available_min": u["available_min"], "booked_min": u["booked_min"],
        "lost_hours": ev["lost_hours"], "dock_events": ev["events"],
        **{k: arr[k] for k in ("arrivals", "late", "on_time", "on_time_rate", "avg_wait_min", "avg_dwell_min", "wait_p90_min")},
        "no_show_rate": ns["no_show_rate"], "no_shows": ns["no_shows"], "scheduled": ns["scheduled"],
        "requests": rq["requests"], "avg_decision_min": rq["avg_decision_min"], "decision_p90_min": rq["decision_p90_min"], "backlog": rq["backlog"],
        "holds_expired": rq["holds_expired"],
        "escalations": es["escalations"], "avg_resolution_min": es["avg_resolution_min"],
        "delay_reports": dl["delay_reports"], "avg_declared_delay_min": dl["avg_declared_delay_min"],
        "bot_resolution_rate": bt["bot_resolution_rate"], "threads": bt["threads"],
        "loads_completed": th["loads_completed"],
        "_tables": {"by_dock": u["by_dock"], "heatmap": u["heatmap"], "by_facility": u["by_facility"], "dock_events": ev["rows"],
                    "delay_causes": dl["causes"], "escalation_reasons": es["by_reason"], "request_mix": rq["mix"]},
    }


def _change(cur: float, old: float) -> float | None:
    return None if not old else round((cur - old) / old * 100, 1)


async def compute(db: AsyncSession, view: str, sc: Scope, p: Period, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    cur = await _scalars(db, sc, p, now)
    prev = await _scalars(db, sc, p.previous, now)
    tables = dict(cur.pop("_tables"))
    prev.pop("_tables")
    extra: dict[str, Any] = {}
    if view == "carrier":
        ct = await queries.carrier_tables(db, sc, p, now)
        tables["by_driver"], tables["by_lane"] = ct["by_driver"], ct["by_lane"]
        for k in ("slot_moves", "slot_cancellations", "offers", "offers_declined", "decline_rate"):
            cur[k] = ct[k]
        pc = await queries.carrier_tables(db, sc, p.previous, now)
        for k in ("slot_moves", "slot_cancellations", "offers", "offers_declined", "decline_rate"):
            prev[k] = pc[k]
    keys = KPI_SETS[view]
    tables["series"] = await queries.series(db, sc, p, now)
    return {
        "view": view, "scope": sc.label,
        "period": {"range": p.key, "from": p.start, "to": p.end, "bucket": p.bucket, "timezone": "Asia/Kolkata"},
        "kpis": {k: {"value": cur[k], "previous": prev[k], "change": _change(float(cur[k]), float(prev[k])), "good_when_up": good} for k, good in keys.items()},
        "extra": {k: cur[k] for k in ("late", "on_time", "arrivals", "no_shows", "scheduled", "threads", "dock_events", "available_min", "booked_min") if k in cur} | extra,
        "series": tables["series"],
        "tables": {k: tables[k] for k in VIEW_TABLES[view] if k != "series" and k in tables},
    }


def table_rows(result: dict[str, Any], name: str) -> tuple[list[str], list[dict]]:
    if name == "series":
        return TABLE_COLUMNS["series"], result["series"]
    if name not in result["tables"]:
        return [], []
    return TABLE_COLUMNS[name], result["tables"][name]
