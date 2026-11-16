# SetuHaul FDE Challenge — build prompt for Claude Code

> How to use: put this file in the root of an empty project folder, copy the SQLite snapshot from the challenge package to `data/setuhaul.db`, and put the brief PDF in `docs/brief.pdf`. Then tell Claude Code: **"Read SETUHAUL_CLAUDE_CODE_PROMPT.md and start Phase 0."**

---

## Your role

You are helping me build my submission for the **SetuHaul Logistics FDE Challenge** (brief in `docs/brief.pdf`; read it fully before writing code). I'm a senior BFSI/payments engineer moving into Forward Deployed Engineer roles. The submission is judged on **reasoning and evidence as much as on code**, so every design choice must be explainable and backed by a query, a test or a transcript.

Work **phase by phase**. At the end of each phase: summarise what you did, show the evidence (query output, test output), list the open questions, and **stop for my review** before starting the next phase. Don't skip ahead.

## What we're building (one sentence)

A driver-facing chat agent, backed by a **deterministic slot-booking engine**, that lets late drivers get a revised dock appointment, **never double-books capacity under concurrent requests**, and escalates to a human with a complete record when it shouldn't decide alone.

## Non-negotiable design rules

1. **The LLM never decides capacity.** It parses messy driver text, asks only for missing facts, explains options and calls tools. Feasibility, holds, confirmations and priority live in plain Python. A prompt must never be the source of truth.
2. **Showing ≠ holding ≠ confirming.** The states are explicit: options shown (no reservation) → `held` (short TTL, default 5 min, configurable) → `confirmed`, plus `released` and `expired`. Only the engine moves a slot between states.
3. **Atomic commits.** SQLite in WAL mode. Every hold and confirm runs inside `BEGIN IMMEDIATE` with a conditional `UPDATE ... WHERE <still available>` and checks the rowcount. Add a partial unique index so the database also blocks two live holds or bookings on one slot. Re-check feasibility at confirm time, because options go stale.
4. **Ask, don't guess.** If the driver → shipment mapping is ambiguous (e.g. a driver with two shipments), ask. If the data contradicts itself, escalate.
5. **Escalate rather than invent.** No feasible slot, safety issues, penalties or compensation, regulated or contradictory loads, or a change of destination facility → create an escalation record and tell the driver honestly what happens next.
6. **Idempotency.** Duplicate or retried chat messages must not create duplicate holds or bookings (key on thread + message id, or a content hash within a short window).
7. **Driver identity comes from the chat thread** (thread → `driver_id`), and a driver can only act on shipments assigned to them. No login or auth system; record that assumption in the decision register.
8. **Design for SetuHaul's scale (6 facilities, 280–360 loads/day, 20–35 messages in a 30-min spike) and test on the snapshot (2 facilities, 9 docks, 21 shipments).** Never hardcode a facility; `facility_id` is a parameter everywhere.
9. **A deterministic clock.** The "current time" is injectable and defaults to the snapshot moment (4 Aug 2026, Asia/Kolkata, +05:30), so tests and replays are reproducible.
10. **Treat the data as evidence, not truth.** Inspect the real schema before coding. Table and column names in the brief's ER diagram are hints; use what the database actually contains.

## Stack

- Python 3.11+, `sqlite3` (stdlib), `pytest`
- An LLM with tool calling, through the Anthropic Python SDK; model name from an env var, `ANTHROPIC_API_KEY` from `.env`
- **Scripted/offline agent mode** (no API key needed) so tests and the scenario run are deterministic. The LLM mode and the scripted mode call the same tools.
- Streamlit for the UI
- Pin library versions in `requirements.txt` and list them in the README (the brief requires this)

## Repo layout (adjust if you have a good reason, and say why)

```
data/setuhaul.db              # original snapshot — never modify; copy to a working DB
docs/                         # brief.pdf + all written deliverables
  01_problem_definition_and_data_audit.md
  02_decision_register.md
  06_client_readout.md
sql/audit/                    # one .sql file per data issue
src/setuhaul/
  db.py                       # connections, WAL, migrations for new tables, clock
  engine/feasibility.py       # what makes a slot feasible for a shipment
  engine/booking.py           # hold / confirm / release / expire — the state machine
  engine/priority.py          # ordering of competing requests
  engine/eta.py               # revised ETA rule + confidence
  tools.py                    # agent tools: thin wrappers returning structured JSON
  agent/llm_agent.py          # LLM tool-calling loop + system prompt
  agent/scripted_agent.py     # deterministic stand-in for tests and replays
  escalation.py               # hand-off records
  ui/app.py                   # Streamlit: driver chat | ops console
tests/
  test_feasibility.py
  test_booking_states.py
  test_concurrency.py         # the integrity proof
  test_idempotency.py
  test_scenarios.py
scenarios/                    # scripted conversations + recorded transcripts
README.md
```

## Agent tools (structured in, structured out)

| Tool | Does |
|---|---|
| `get_driver_context(thread_id)` | driver, their active shipments, current appointment, vehicle and load type, destination facility; flags ambiguity |
| `update_eta(shipment_id, eta, source, confidence)` | records a driver-declared ETA without overwriting history |
| `find_feasible_slots(shipment_id, earliest, latest, limit=3)` | ranked feasible options with reasons; never reserves |
| `hold_slot(shipment_id, slot_id, request_id)` | atomic hold with TTL; returns `held` or `unavailable` + alternatives |
| `confirm_booking(shipment_id, slot_id, request_id)` | re-checks, commits, releases the old appointment, returns a booking ref |
| `release_hold(shipment_id, slot_id)` | driver declines or changes their mind |
| `escalate_to_human(shipment_id, reason, context)` | creates a complete hand-off record |

New tables (as migrations on the working copy): `slot_holds`, `booking_requests`, `escalations`, `processed_messages`, `audit_log`.

---

## Phases

### Phase 0 — Orient (no code yet)
- Read `docs/brief.pdf` end to end.
- Inspect `data/setuhaul.db`: list all 18 tables, row counts, the views (`v_latest_eta`, `v_slot_availability`, `v_inbound_operational_state`, `v_current_facility_queue`) and indexes, including the partial unique indexes.
- Write `docs/schema_notes.md`: the real schema, how it maps to the brief's six stages and its entity model, and your first list of suspected data issues.
- Propose the plan for Phase 1 and stop.

### Phase 1 — Problem definition + data audit (deliverable 1)
- Sort what's known into **facts / estimates / assumptions / unknowns**.
- Find the data issues and **prove each with a query** in `sql/audit/NN_name.sql`. Look at least for: slots overlapping blocked/maintenance/breakdown windows; cancelled or no-show bookings and what they mean for availability; pending-confirmation appointments; drivers with more than one shipment; conflicting ETAs from different sources; dock and load-type mismatches; duplicate chat messages; appointments whose state conflicts with gate check-ins; what the two partial unique indexes **do not** prevent.
- For each issue, record the query, the result, the business impact and how the system will handle it.
- Use the seed "ladder" cases from the brief (THR011/SHP1017, THR003/SHP1013/THR010/DRV004, SHP1010/SHP1015/SHP1016/RULE005, SHP1006/SHP1012/SHP1013/SHP1014/SHP1009, SHP1005/APT1008/THR001/THR009/SHP1002, SHP1015/THR005/OM004, SHP1002/SHP1003/SHP1004/SHP1006) to anchor the audit.

### Phase 2 — Decision register draft (deliverable 2)
- Answer all 13 decisions from the brief (understand → decide → commit → fail safely → prove), each with **answer, reason, trade-off and the evidence we'll produce**. Mark the answers that are still provisional. Code must follow these decisions; update the register if the code forces a change.

### Phase 3 — Capacity engine + integrity proof (the core)
- Feasibility rules (facility, dock compatibility, blocked windows, timing vs ETA and the driver's latest finish, facility rules), the booking state machine, the priority policy and the ETA rule.
- `test_concurrency.py`: **N workers (threads and separate processes, each with its own connection) race for the same slot**; assert exactly one confirmed booking, every loser gets a clean `unavailable` plus alternatives, and the invariants hold afterwards. Also test: a hold expiring mid-conversation, confirming a stale option, a duplicate message, a retry after a timeout.
- Run the tests and show the output. This phase isn't done until they pass.

### Phase 4 — Agent tools + conversation layer
- Implement the tools, the scripted agent, then the LLM agent with a tight system prompt: collect only the missing facts (delay vs repair time, latest finish, which shipment), never promise before a hold, explain refusals in plain words, escalate per the rules.
- Keep the clarification turns low; the brief measures them.

### Phase 5 — UI (Streamlit)
Two views over the same database, plus a side-by-side demo mode:
- **Left: driver chat** — choose which driver/thread you're acting as (it stands in for WhatsApp), quick-reply chips for options, and a faint line under each reply showing which tools ran.
- **Right: ops console** — a facility dropdown; a live dock board (docks × hours) coloured by open / held (with countdown) / confirmed / blocked / at risk; the escalation queue with an expandable hand-off record and "Assign to me"; the audit log; an integrity badge (conflicts = 0); a "simulate race" button.
- No login, no company website, no coordinator slot-assignment workflow. Coordinators only pick up escalations.

### Phase 6 — Scenario run (deliverable 4)
A scripted, replayable run (`python -m setuhaul.scenarios`) that saves transcripts and shows, in order: a delay plus clarification questions; comparing later options; several requests against one facility; at least two requests competing for one slot; an option changing or disappearing mid-conversation; and ending with at least one escalation (no safe automatic outcome). Report the brief's measures for the run (time to outcome, share resolved without takeover, conflicting allocations, options later infeasible, clarification turns, slot utilisation, priority-policy violations).

### Phase 7 — Client readout + README (deliverables 5 & 6)
- `docs/06_client_readout.md`: plain language for the head of operations and a warehouse planner — the policy, the limits (no live GPS, ETAs are declared), the open risks (coordinator load in spikes), and what production would add (WhatsApp Business webhook, Postgres with row locks). No jargon.
- README: setup, how to run the tests, the UI and the scenario run, pinned versions, and the architecture diagram.

### Optional Phase 8 — facility scheduling tool
Only after everything above passes. Start with a simple dispatch rule and a transparent score. Use OR-Tools CP-SAT only if you can explain why; compare it against the simple rules on the competing-trucks snapshot (SHP1002, SHP1003, SHP1004, SHP1006), with in-progress unloading treated as fixed.

---

## Out of scope (don't build)
Authentication/login, a company website, mobile apps, push notifications, network optimisation, carrier selection or pricing, autonomous safety decisions, customs or hazmat workflows, approving penalties.

## Definition of done
- All tests pass, including the concurrency proof, with output saved in `docs/evidence/`.
- Every data issue in the audit has a runnable query.
- All 13 decisions are answered and match the code.
- The scenario run replays deterministically and ends in an escalation.
- A non-technical ops lead can read the client readout in 5 minutes.
