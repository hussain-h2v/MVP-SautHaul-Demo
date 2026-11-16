from __future__ import annotations

import json
from pathlib import Path

from setuhaul.clock import SimClock
from setuhaul.db import connect
from setuhaul.scheduler_tool import propose_schedule

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "setuhaul_freight_operations.db"
SHIPMENT_IDS = ["SHP1002", "SHP1003", "SHP1004", "SHP1006"]
RUN_TS = "2026-08-04T09:00:00+05:30"
JSON_PATH = ROOT / "scenarios" / "phase8_scheduler_comparison.json"
REPORT_PATH = ROOT / "scenarios" / "phase8_scheduler_comparison.md"


def build_comparison() -> dict:
    conn = connect(DB_PATH)
    try:
        return propose_schedule(
            conn,
            SimClock(RUN_TS),
            "FAC-JAI-01",
            shipment_ids=SHIPMENT_IDS,
        )
    finally:
        conn.close()


def render_report(result: dict) -> str:
    lines = [
        "# Phase 8 facility scheduling comparison",
        "",
        f"- Facility: `{result['facility_id']}`",
        f"- As of: `{RUN_TS}`",
        f"- Competing shipments: {', '.join(f'`{sid}`' for sid in SHIPMENT_IDS)}",
        f"- Rule: {result['objective']}",
        "",
        "## Fixed in-progress work",
        "",
    ]
    for fixed in result["fixed_in_progress"]:
        lines.append(
            f"- `{fixed['shipment_id']}` remains at dock `{fixed['dock']}`; "
            f"estimated finish `{fixed['estimated_finish']}`; rescheduled: no."
        )

    lines.extend(["", "## Scorecard", "", "| Proposal | Priority-weighted wait (min) | Total wait (min) | Average wait (min) | Missed appointments |", "|---|---:|---:|---:|---:|"])
    for key, label in (("priority_rule", "Earliest start + priority tie-break"), ("naive_fcfs", "FCFS baseline")):
        score = result[key]
        lines.append(
            f"| {label} | {score['priority_weighted_wait_min']:.1f} | "
            f"{score['total_wait_min']:.1f} | {score['avg_wait_min']:.1f} | "
            f"{score['missed_appointments']} |"
        )

    lines.extend(["", "## Proposed order", ""])
    for key, label in (("priority_rule", "Priority-aware"), ("naive_fcfs", "FCFS")):
        lines.extend([f"### {label}", ""])
        for entry in result[key]["entries"]:
            lines.append(
                f"- `{entry['shipment_id']}` → dock `{entry['dock']}`, "
                f"{entry['start'][11:16]}–{entry['end'][11:16]}, "
                f"wait {entry['waited_min']:.1f} min, "
                f"missed current appointment: {entry['missed_own_appointment']}."
            )
        lines.append("")

    lines.extend([
        "## Interpretation",
        "",
        "The rule is a transparent greedy proposal, not a capacity reservation or a global optimizer. "
        "It selects the earliest feasible start and uses shipment priority only when feasible starts tie; "
        "ETAs, dock compatibility, and the fixed in-progress unload constrain the order. The scorecard "
        "shows the priority-weighted wait (`wait minutes × priority weight`), total and average wait, and "
        "missed appointments separately rather than hiding trade-offs in one arbitrary composite number.",
        "",
        "On this snapshot the competing schedules are expected to be similar because the two waiting "
        "trucks are ready at different times and SHP1006 has a later ETA. The rule should not claim a "
        "benefit where the measured scorecard shows none.",
        "",
        "CP-SAT was not added: after fixing SHP1002 there are only three movable shipments in this "
        "comparison, and the transparent rule ties the FCFS scorecard. This example provides no evidence "
        "that a heavier solver would improve the result.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    result = build_comparison()
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(render_report(result), encoding="utf-8")
    print(render_report(result))
    print(f"JSON evidence: {JSON_PATH}")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
