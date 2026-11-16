# Problem definition and data audit

## 1. Facts, estimates, assumptions, unknowns

| Category | Statement |
|---|---|
| Fact | The snapshot is a single-day operational slice with 2 facilities, 9 docks, and 21 shipments. |
| Fact | `appointment_slots` and `appointments` are the core capacity and booking tables; the partial unique indexes permit at most one live appointment per slot and one current active appointment per shipment. |
| Fact | ETA history is captured in `eta_updates`, with a view `v_latest_eta` that chooses the most recent source and default fallback values. |
| Fact | Driver messages are recorded in `chat_threads` and `chat_messages`, including `is_duplicate` and `requires_human_review` flags. |
| Fact | Dock disruptions are materialised in `dock_status_events` and overlap with slot rows. |
| Fact | Some shipments show `PENDING_CONFIRMATION` or `CONFIRMED` appointments even while the shipment is still `IN_TRANSIT`, which means booking state and shipment state are only loosely coupled. |
| Estimate | A late driver request can be resolved safely if the system asks for the missing fact (delay vs repair time, latest unload finish, exact shipment) before offering a slot. |
| Assumption | Driver identity in the chat layer is derived from the thread, and no auth layer is present. |
| Assumption | A shown slot is not a held reservation; it must be materialised via a deterministic hold/confirm flow. |
| Assumption | The “current time” should be injected rather than read from the wall clock for testing and replay. |
| Unknown | The exact internal priority weighting for competing requests must still be designed. |
| Unknown | The real-world SLA for hold expiry is not in the data and must be treated as a policy decision. |

## 2. Data issues investigated and their business impact

### A. Slots overlapping blocked or maintenance windows

Evidence: `sql/audit/01_slots_overlapping_blocked_windows.sql`

Observed result:
- `SLOT-JAI-015` and `SLOT-JAI-016` both overlap with `CAPACITY_REDUCTION` on `DOCK-JAI-D2`
- `SLOT-JAI-030` overlaps with `BREAKDOWN` on `DOCK-JAI-D3`

Impact:
- A slot can appear available in the view while a dock is effectively blocked.
- The engine must consult the active blocked windows before showing or confirming any slot.

Handling rule:
- Never treat a slot as feasible if its time window overlaps a live blocked event on the same dock.

### B. Cancelled or no-show bookings remain part of the appointment history

Evidence: `sql/audit/02_cancelled_no_show_booking_meaning.sql`

Observed result:
- `SHP1008` is `CANCELLED`
- `SHP1018` is marked `NO_SHOW`
- some historical rows are `CANCELLED` even though the shipment still appears in the operational state

Impact:
- A stale cancelled or no-show record must not be mistaken for current capacity.
- It is operational evidence, not a live booking.

Handling rule:
- Cancelled/no-show records are historical evidence; they influence operations and escalations but do not provide current capacity.

### C. Pending-confirmation appointments require explicit lifecycle handling

Evidence: `sql/audit/03_pending_confirmation_appointments.sql`

Observed result:
- `SHP1013` and `SHP1014` are still in `PENDING_CONFIRMATION`

Impact:
- A slot may be reserved in the conversation layer but not yet accepted at the warehouse level.
- This state can cause stale options or double holdings if the engine does not revalidate.

Handling rule:
- Treat pending confirmation as an internal hold state only; the engine re-checks before final confirm and can release or expire it.

### D. Drivers can have multiple active shipments on the same day

Evidence: `sql/audit/04_drivers_with_multiple_active_shipments.sql`

Observed result:
- `DRV003`, `DRV004`, `DRV006`, and `DRV007` each have 2 active shipments

Impact:
- A message without a shipment identifier is ambiguous.
- The system must ask which shipment is being modified rather than guessing.

Handling rule:
- If the thread has no shipment mapping and the driver has >1 active load, ask which shipment before offering options.

### E. ETA history can change over time and must be resolved deterministically

Evidence: `sql/audit/05_conflicting_eta_sources.sql`

Observed result:
- Some shipments have multiple ETA update rows over time; in this snapshot the updates are all from the same source type (`DRIVER_DECLARED`) but the declared ETA changes across messages.

Impact:
- A shipment can appear to have conflicting ETA signals if the system does not apply a deterministic rule to the latest update.

Handling rule:
- Always choose the latest record by timestamp, keep the history, and treat source changes as a separate escalation trigger if they become inconsistent in later data.

### F. Dock and load-type compatibility is not enforced by schema, so it must be code-enforced

Evidence: `sql/audit/06_dock_load_type_mismatch.sql`

Observed result:
- For this snapshot, there are no direct mismatches in currently active appointments.
- However, the invariant is not database-enforced by a foreign-key or check constraint.

Impact:
- The database permits logically incompatible rows if they are inserted outside the intended business flow.

Handling rule:
- Feasibility logic must check dock type, refrigeration capability, and facility rules before accepting a slot.

### G. Duplicate or retried chat messages are real and must be idempotent

Evidence: `sql/audit/07_duplicate_chat_messages.sql`

Observed result:
- `MSG015` in `THR009` is flagged as `is_duplicate = 1`

Impact:
- Retried or repeated messages can trigger duplicate holds or duplicate requests if the system is not idempotent.

Handling rule:
- Key retries by thread + message id or a short message hash and ignore duplicates within a defined window.

### H. Gate check-ins and appointment planning can drift and should be treated as operational exceptions

Evidence: `sql/audit/08_gate_checkin_vs_appointment_conflict.sql`

Observed result:
- There are no active row-level conflicts in this snapshot, but the logic must still guard for them.

Impact:
- A truck can be physically at a different dock or queue state than the currently booked appointment indicates.

Handling rule:
- If the check-in state and appointment state disagree materially, escalate rather than automatically reallocate.

### I. The partial unique indexes do not cover ambiguous conversations or stale requests

Evidence: `sql/audit/09_partial_unique_index_gaps.sql`

Observed result:
- Some chat threads have `shipment_id IS NULL`, which means the thread is ambiguous even though appointment integrity is enforced.

Impact:
- Slot uniqueness is enforced, but message interpretation and context assignment are still weak points.
- This is exactly where stale-show and duplicate-retry problems originate.

Handling rule:
- The engine must guard the conversation layer with explicit shipment resolution and idempotency, not just database uniqueness.

## 3. Ladder cases anchored to the challenge seed

The audit was checked against the ladder cases in the brief, including:

- THR011 / SHP1017
- THR003 / SHP1013 / THR010 / DRV004
- SHP1010 / SHP1015 / SHP1016 / RULE005
- SHP1006 / SHP1012 / SHP1013 / SHP1014 / SHP1009
- SHP1005 / APT1008 / THR001 / THR009 / SHP1002
- SHP1015 / THR005 / OM004
- SHP1002 / SHP1003 / SHP1004 / SHP1006

The recurring pattern is that the real risk is not just capacity math; it is ambiguous intent, stale options, and concurrency across shared slot inventory.

## 4. Proposed handling philosophy for the implementation phase

The implementation should be deterministic and conservative:

1. Ask for the missing fact if the shipment or timing is ambiguous.
2. Never reserve capacity while showing options.
3. Hold only with a short TTL and a unique request id.
4. Re-check feasibility and compatibility when confirming.
5. Escalate whenever the data is contradictory or a human review is required.

This is the boundary between the problem-definition phase and the engineering phase.
