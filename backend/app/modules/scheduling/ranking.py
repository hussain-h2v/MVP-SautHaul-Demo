"""Pure ranking policy (spec section 5). Two uses:

* rank_options: order one shipment's feasible options (earliest and least disruptive first).
* rank_requests: order competing requests for scarce capacity. Policy, in order: trucks already
  unloading are fixed and never moved; higher priority; trucks whose current appointment is lost;
  longest waiting / earliest gate-in; earliest start. Exact ties are flagged for a human.
Weights come from system_settings.ranking_weights and are applied as a weighted score so operations can tune them."""
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.scheduling.feasibility import Option

PRIORITY_RANK = {"CRITICAL": 4, "HIGH": 3, "NORMAL": 2, "LOW": 1}
DEFAULT_WEIGHTS = {"priority": 1000, "lost_appointment": 100, "waiting": 10, "earliest_start": 1}


def _hhmm(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


def rank_options(options: list[Option], *, eta: datetime | None, tz) -> list[Option]:
    """Approval-free first, then earliest start, then least wasted time, then dock code (stable)."""
    ordered = sorted(options, key=lambda o: (o.needs_planner_approval, o.start, o.wasted_min, o.dock_code))
    for i, o in enumerate(ordered, start=1):
        o.rank = i
        parts = []
        if i == 1:
            parts.append("Earliest compatible slot" + (f" after the {_hhmm(eta, tz)} ETA" if eta else ""))
        else:
            gap = int((o.start - ordered[0].start).total_seconds() // 60)
            parts.append(f"Starts {gap} min after the best option")
        if o.wasted_min > 0:
            parts.append(f"{o.wasted_min} min of the window is spare")
        if len([r for r in o.reasons if r.startswith("COMBINES")]):
            parts.append("combines consecutive windows because the load needs more than one")
        if o.needs_planner_approval:
            parts.append("needs planner approval (starts after the last allowed start), so it ranks below approval-free options")
        o.explanation = "; ".join(parts) + "."
    return ordered


@dataclass
class RequestFacts:
    id: object
    priority_code: str
    option_start: datetime
    is_unloading: bool = False
    lost_appointment: bool = False
    waiting_min: int = 0


@dataclass
class RankedRequest:
    id: object
    rank: int
    score: float
    fixed: bool
    tie_with_next: bool = False
    reasons: list[str] = field(default_factory=list)


def rank_requests(requests: list[RequestFacts], *, now: datetime, weights: dict | None = None) -> list[RankedRequest]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    def score(r: RequestFacts) -> float:
        wait_h = r.waiting_min / 60
        until_h = max(0.0, (r.option_start - now).total_seconds() / 3600)
        return (PRIORITY_RANK.get(r.priority_code, 2) * w["priority"] + (w["lost_appointment"] if r.lost_appointment else 0)
                + wait_h * w["waiting"] - until_h * w["earliest_start"])

    scored = sorted(((r, score(r)) for r in requests), key=lambda t: (not t[0].is_unloading, -t[1], t[0].option_start))
    out: list[RankedRequest] = []
    for i, (r, s) in enumerate(scored, start=1):
        reasons = []
        if r.is_unloading:
            reasons.append("Already unloading: fixed, never moved")
        reasons.append(f"{r.priority_code} priority")
        if r.lost_appointment:
            reasons.append("current appointment is lost")
        if r.waiting_min:
            reasons.append(f"waiting {r.waiting_min} min")
        out.append(RankedRequest(id=r.id, rank=i, score=round(s, 3), fixed=r.is_unloading, reasons=reasons))
    for a, b in zip(out, out[1:], strict=False):
        if not a.fixed and not b.fixed and abs(a.score - b.score) < 1e-9:
            a.tie_with_next = True
            a.reasons.append("tie with the next request: needs a human decision")
    return out
