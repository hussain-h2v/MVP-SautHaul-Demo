# Phase 0 — schema notes and orientation

This working copy was built from the public SetuHaul challenge repo, because the workspace snapshot provided here did not contain the actual `brief.pdf` or the SQLite package. The database was copied to `data/setuhaul.db` and the available README/docs were treated as the brief-equivalent source of truth for this phase.

## Snapshot evidence

- Database: `data/setuhaul.db`
- Snapshot day: 2026-08-04, timezone `Asia/Kolkata` (`+05:30`)
- Scale: 2 facilities, 9 docks, 21 shipments
- There are 18 tables and 4 operational views.

## 1) Table inventory and row counts

| Table | Rows | Notes |
|---|---:|---|
| `appointment_slots` | 106 | hourly/90-minute dock slots across facilities |
| `appointments` | 20 | active and historical booking records |
| `carriers` | 4 | logistics carriers |
| `chat_messages` | 20 | driver/ops chat events |
| `chat_threads` | 12 | driver conversations by thread |
| `dock_status_events` | 3 | breakdown/maintenance/capacity reduction events |
| `docks` | 9 | dock-level capacity + type metadata |
| `driver_exceptions` | 10 | delay/exception workflow records |
| `drivers` | 15 | driver roster |
| `eta_updates` | 12 | ETA revisions with source and confidence |
| `facilities` | 2 | Jaipur and Gurgaon facilities |
| `facility_checkins` | 5 | gate/queue/dock arrival state |
| `facility_contacts` | 5 | facility contacts and emergency roles |
| `facility_rules` | 6 | per-facility operational rules |
| `operational_messages` | 5 | outbound operational comms |
| `shipments` | 21 | loads and job records |
| `vehicle_types` | 5 | vehicle classes |
| `vehicles` | 15 | truck roster |

## 2) Operational views

These are the core views used by the scheduling and conversation logic.

### `v_latest_eta`

Purpose: latest ETA per shipment, with `original_eta_ts`, `effective_eta_ts`, and source/confidence.

Key logic:
- uses `ROW_NUMBER() OVER (PARTITION BY shipment_id ORDER BY created_at DESC, eta_update_id DESC)`
- falls back to `shipments.latest_eta_ts` / `shipments.original_eta_ts` if no update exists
- exposes `eta_source`, `eta_confidence`, and `delay_reason_code`

Sample rows show the model is already tracking a mix of original plan, driver-declared ETA, and delay reasons.

### `v_slot_availability`

Purpose: current slot status by dock and appointment.

Status values are derived in SQL:
- `BLOCKED` when slot status is not `OPEN`
- `OCCUPIED` when a current appointment is present
- otherwise `AVAILABLE`

This is a good fit for feasibility checks because it collapses slot state into one queryable view.

### `v_inbound_operational_state`

Purpose: a shipment-centric operational status snapshot combining ETA, active appointment, dock assignment, facility check-in, and queue state.

It joins:
- `shipments` + `v_latest_eta`
- current appointment (`is_current = 1`, status in `PENDING_CONFIRMATION/CONFIRMED/IN_PROGRESS`)
- slot and dock
- `facility_checkins` and actual dock

This is the best single view for driver state + dock readiness + ETA cross-checks.

### `v_current_facility_queue`

Purpose: queue view for waiting shipments, filtered to `queue_state` values in `('WAITING_EARLY','WAITING_LATE','WAITING_DOCK_UNAVAILABLE','CALLED_TO_DOCK')`.

This provides the live queue and makes the facility board actionable without separate per-queue logic.

## 3) Indexes and integrity constraints

### Important non-unique indexes

`ix_chat_messages_thread_time` on `chat_messages(thread_id, message_ts)`
`ix_eta_updates_shipment_created` on `eta_updates(shipment_id, created_at DESC)`
`ix_exceptions_status_time` on `driver_exceptions(exception_status, reported_at)`
`ix_shipments_destination_status` on `shipments(destination_facility_id, current_status)`
`ix_slots_facility_time` on `appointment_slots(facility_id, slot_start_ts, slot_end_ts)`

These support message chronology, ETA history, exception triage, and slot lookups.

### Partial unique indexes (critical for concurrency and booking integrity)

```sql
CREATE UNIQUE INDEX ux_active_appointment_per_slot
ON appointments(slot_id)
WHERE appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
```

```sql
CREATE UNIQUE INDEX ux_current_active_appointment_per_shipment
ON appointments(shipment_id)
WHERE is_current = 1
  AND appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')
```

These are exactly the constraints that prevent a slot from being double-booked and prevent a shipment from carrying two active appointments simultaneously. They are partial indexes, so they only police the active states rather than all historical records.

A key phase-1 audit task is to prove what they do not prevent: e.g. stale holds, multi-shipment ambiguity, or duplicate retries that are not the same event in a different thread.

## 4) Entity model and mapping to the six-stage brief

The database is a plausible operational state machine rather than a pure relational booking model. The main entities map cleanly to the brief's six stages:

1. Driver / shipment identity
   - `drivers`, `shipments`, `vehicles`, `carriers`
2. Facility capacity and slot inventory
   - `facilities`, `docks`, `appointment_slots`
3. Booking lifecycle
   - `appointments` with states `PENDING_CONFIRMATION -> CONFIRMED -> IN_PROGRESS -> COMPLETED/CANCELLED/NO_SHOW`
4. ETA / uncertainty / exception reporting
   - `eta_updates`, `driver_exceptions`, `chat_threads`, `chat_messages`
5. Operational evidence and queue tracking
   - `facility_checkins`, `dock_status_events`, `operational_messages`
6. Human escalation / follow-up
   - `driver_exceptions.exception_status`, `chat_threads.thread_status`, `operational_messages.delivery_status`

The underlying design suggests a deterministic engine should not trust the LLM to pick a slot. It should be fed specific driver facts and then enforce feasibility against real rows and partial unique constraints.

## 5) First suspects from the data (Phase 1 candidates)

These are not final conclusions yet; they are the leading issues to prove in the audit phase.

1. Ambiguous shipment resolution
   - Several drivers have more than one active shipment in the same day.
   - `chat_threads` can be associated with a shipment or left blank (`thread.shipment_id IS NULL`).
   - This is a primary source of wrong-driver / wrong-shipment decision-making.

2. Duplicate or retried chat messages
   - `chat_messages.is_duplicate` exists and there are likely duplicate message patterns.
   - A retried message must not create another booking or hold.

3. Conflicting or stale ETA records
   - `v_latest_eta` and `eta_updates` suggest multiple ETA sources.
   - `source_type` includes driver, operations, warehouse, and original plan; they must be reconciled deterministically.

4. Blocked / maintenance windows and slot feasibility
   - `dock_status_events` and `appointment_slots.slot_status` overlap in the real logic.
   - A feasibility query must treat blocked windows as active capacity loss even if the SQL row is not directly a booking.

5. Pending-confirmation slots versus active queue state
   - `appointments` can still be `PENDING_CONFIRMATION` while a shipment is in queue.
   - This is exactly the state where a stale option or duplicate acceptance can start to create a conflict.

6. Facility check-ins vs actual dock mismatch risk
   - `facility_checkins.actual_dock_id` can differ from the planned dock; the schema does not enforce them to match.
   - This is a human-review trigger, not a silent auto-approval path.

7. Operational message failures and missing contact data
   - Some facility contacts have no e-mail.
   - Some operational messages in the seed set are marked `FAILED`.
   - The system must treat failed delivery as evidence of no confirmation, not as success.

8. Unclear or contradictory “delay” language in messages
   - Certain driver messages are flagged as requiring human review.
   - The logic should ask for the missing fact rather than infer one from natural-language ambiguity.

## 6) Proposed Phase 1 plan

Phase 1 should be an audit and evidence phase, not a coding phase. The planned outputs are:

1. Sort all facts into facts / estimates / assumptions / unknowns.
2. Run the data-quality SQL checks to prove each issue with a reproducible query.
3. Record the business impact and set the operational handling rule for each issue.
4. Use the seeded ladder cases as fixed anchor examples (THR011 / SHP1017, THR003 / SHP1013 / THR010 / DRV004, etc.) to ground the audit in the real challenge data.
5. Stop before implementation and wait for review.

This is the boundary between investigation and engineering, and it is where the brief asks for reasoned evidence before a single `BEGIN IMMEDIATE` or slot hold is written.
