"""Rule-based recommendation for a coordinator request. Pure: no database, no AI. AI explanations arrive in M7 and
may only add wording; the action itself is always derived from these rules and a human still decides."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class HeldFacts:
    feasible: bool
    needs_planner_approval: bool
    problems: list[str]
    start: datetime
    slot_code: str
    expired: bool = False


@dataclass
class OptionFacts:
    slot_ids: list
    slot_codes: list[str]
    start: datetime
    needs_planner_approval: bool


@dataclass
class Recommendation:
    action: str
    slot_ids: list = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    impact: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    source: str = "rules"


def recommend(*, held: HeldFacts | None, options: list[OptionFacts], eta_ts: datetime | None, eta_confidence: str | None,
              eta_range: bool, requires_human_review: bool, priority: str, replan: bool, current_slot_code: str | None,
              competing_for_same_slot: int = 0, now: datetime) -> Recommendation:
    flags: list[str] = []
    if eta_confidence == "LOW":
        flags.append("ETA_VAGUE")
    if eta_range:
        flags.append("ETA_RANGE")
    if requires_human_review and "ETA_VAGUE" not in flags and "ETA_RANGE" not in flags:
        flags.append("NEEDS_HUMAN_REVIEW")
    if priority in ("CRITICAL", "HIGH"):
        flags.append(f"{priority}_PRIORITY")
    if eta_ts is not None and eta_ts < now - timedelta(minutes=30):
        flags.append("ETA_STALE")
    if competing_for_same_slot > 0:
        flags.append("COMPETING_REQUESTS")

    def impact_for(start: datetime, codes: list[str], approval: bool) -> list[str]:
        out = [f"Takes {', '.join(codes)} from {start:%H:%M}"]
        if current_slot_code and not approval:
            out.append(f"Releases the driver's current slot {current_slot_code} for other trucks")
        if approval:
            out.append("Needs planner confirmation; the current slot is kept until then")
        if competing_for_same_slot:
            out.append(f"{competing_for_same_slot} other request(s) are competing for this slot")
        return out

    if held is not None and held.feasible and not held.expired:
        reasons = ["The held slot is still free and compatible", "Re-validated just now against rules, docks and ETA"]
        if replan:
            reasons.append("The old booking was invalidated by a dock event")
        return Recommendation("approve", [], reasons, impact_for(held.start, [held.slot_code], held.needs_planner_approval), flags)
    if options:
        top = options[0]
        reasons = []
        if held is not None:
            reasons.append("The held option is no longer feasible" + (f" ({', '.join(held.problems)})" if held.problems else ""))
            if held.expired:
                reasons.append("The hold expired")
        elif replan:
            reasons.append("The booking was invalidated; a new slot is needed")
        reasons.append("The best alternative is the earliest compatible slot after the ETA")
        if requires_human_review and not replan and held is None:
            return Recommendation("hold", [], ["The ETA is vague or a range: ask the driver to confirm before committing a slot",
                                               f"Best option so far: {', '.join(top.slot_codes)} at {top.start:%H:%M}"],
                                  ["Nothing is reserved yet"], flags)
        return Recommendation("suggest", list(top.slot_ids), reasons, impact_for(top.start, top.slot_codes, top.needs_planner_approval), flags)
    return Recommendation("escalate", [], ["No compatible, free slot exists in the search window",
                                           "Do not invent an answer: hand over to a human with the full record"],
                          ["The driver keeps the current booking, if any"], flags)
