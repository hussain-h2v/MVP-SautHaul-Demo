"""Prometheus metrics for the booking engine and platform (spec section 13)."""
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

registry = CollectorRegistry()
SLOT_TAKEN = Counter("setuhaul_slot_taken_total", "place_hold calls rejected because the slot was taken", registry=registry)
HOLDS = Counter("setuhaul_holds_total", "Holds by outcome", ["outcome"], registry=registry)
APPROVALS = Counter("setuhaul_approvals_total", "Coordinator/planner decisions", ["decision"], registry=registry)
APPROVAL_LATENCY = Histogram("setuhaul_approval_latency_seconds", "Request creation to decision", registry=registry,
                             buckets=(30, 60, 120, 300, 600, 1800, 3600))
INFEASIBLE_AT_REVALIDATION = Counter("setuhaul_options_infeasible_total",
                                     "Options found infeasible when re-validated", registry=registry)
ESCALATIONS = Counter("setuhaul_escalations_total", "Escalations created", ["reason"], registry=registry)
SWEEP = Counter("setuhaul_sweep_total", "Rows handled by the sweeper", ["kind"], registry=registry)
SSE_CONNECTIONS = Gauge("setuhaul_sse_connections", "Open SSE connections", registry=registry)


def render() -> bytes:
    return generate_latest(registry)
