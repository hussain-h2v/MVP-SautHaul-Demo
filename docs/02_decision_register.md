# Decision register draft

This document records the decisions we will encode in the engine and conversation layer. It is intentionally written as a draft: some values are fixed by the data and the brief, and a few remain provisional until the working code and scenario run prove them in practice.

## 1. What must we collect before showing options?

Answer: Before we call the slot search, we need three things: a resolved shipment, a usable current ETA, and any explicit constraint the driver gave (for example, a latest unload finish time or a leave-by time). We do not ask for any fact the backend already knows, such as required dock type, weight, priority, or facility rules.

Reason: The brief’s separation between “ask the driver” and “check the backend” is explicit. Asking the driver for a fact the database already stores creates friction and can lead to inconsistent choices.

Trade-off: This reduces clarification turns, but it requires the system to trust the DB as the source of truth for capacity metadata and route logic.

Evidence to produce: scenario transcripts showing the driver receives only missing-fact requests, not backend facts; query evidence from `shipments`, `docks`, `facilities`, and `facility_rules` for the same shipment context.

Status: Fixed.

## 2. How does a conversation bind to the right driver, shipment, and appointment?

Answer: We bind by chat thread to `driver_id`, and then resolve to a single `shipment_id` before any tool call that needs one. If a driver has more than one active shipment and the thread does not already name which one, we ask the driver instead of guessing, and we store the answer back on `chat_threads.shipment_id`.

Reason: The snapshot contains drivers with multiple active shipments. Guessing would create wrong-load reasoning and hidden wrong-slot offers.

Trade-off: More clarification turns when the thread is ambiguous, but far lower risk of wrong bookings or rebooking the wrong load.

Evidence to produce: audit query for drivers with >1 active shipment, plus scenario replay for THR010 / DRV004 showing the clarification request instead of a guessed assignment.

Status: Fixed.

## 3. How do we set the revised ETA and how sure are we?

Answer: Every revised ETA is recorded as a new row in `eta_updates` with explicit source and confidence. We treat a clean clock time as higher confidence, a delay in minutes as medium confidence, and a vague “repair time” or “late by X” phrasing as lower confidence until the driver clarifies the meaning. We update `shipments.latest_eta_ts` in the same transaction so it stays aligned with the effective ETA view.

Reason: The data and brief distinguish “repair time” from “arrival change.” A vague message can mean either a new arrival time or a delay while the vehicle is still moving.

Trade-off: Lower-confidence ETA values can lead to fewer or more conservative recommended slots, but they avoid pretending the ETA is certain when it is not.

Evidence to produce: `v_latest_eta` query and scenario traces for the ambiguous delay cases, including THR003 and THR010.

Status: Provisional until the scenario run proves the confidence logic in practice.

## 4. What makes a slot feasible for a shipment?

Answer: A slot is feasible only if all of the following are true: the slot is still `OPEN` in the current capacity model, not blocked by a live maintenance/breakdown/capacity event, not already occupied by a live booking, dock compatibility matches the shipment’s required dock type and refrigeration requirement, vehicle weight stays within the dock limit, and the slot does not violate the facility’s hard operating rules or the driver’s stated latest finish time.

Reason: “Available” in the SQL view means only one part of feasibility. A slot can be technically open but still wrong for the load, outside hours, or blocked by a facility rule.

Trade-off: This is conservative. It may shrink the option set and increase escalations, but it prevents false promises and silent rule violations.

Evidence to produce: feasibility queries and test cases for reefer-only loads, heavy-dock loads, and blocked slots; scenario run proving a zero-feasible-slot branch escalates rather than inventing a slot.

Status: Fixed.

## 5. What does “available” mean while another driver is deciding?

Answer: We model three explicit states: shown, held, and confirmed. Shown is read-only and does not reserve anything. Held is the short-lived reservation created by a valid booking request with TTL. Confirmed is the final commitment. The slot must be re-checked at commit time; a slot offered earlier is not trusted merely because it was shown.

Reason: The brief specifically states that showing ≠ holding ≠ confirming. A slot shown to one driver must not become a hidden reservation.

Trade-off: Re-checking means a slot can disappear between show and confirm. That is correct, and it is a failure-safe behavior.

Evidence to produce: tests for stale option rejection and expiry, and the concurrency proof showing all losers receive a clean “unavailable” response with alternatives.

Status: Implemented with a configurable 5-minute default (`HOLD_TTL_MINUTES`); the expiry regression test verifies release at the TTL boundary.

## 6. When does an option become a hold, request, reservation, or confirmed booking?

Answer: A shown option is read-only. A hold is created only when the engine writes a transactionally safe booking request or active appointment state. A confirmed booking is final only after re-validation and commit. If a facility rule or manual-approval rule applies, the system keeps that outcome in a pending or escalated state instead of silently approving it.

Reason: The brief emphasizes that the LLM is not the source of truth and that decisions must live in Python/SQLite logic, not in prompt behavior.

Trade-off: This slows down the interaction and makes more explicit states than a naive “one click = booked” flow; the benefit is correct accountability and safe concurrency.

Evidence to produce: engine-level tests for hold → confirm → release and for stale confirmation refusal.

Status: Fixed.

## 7. How do we order simultaneous requests when capacity is short?

Answer: We separate slot races from facility dispatch suggestions. For one slot, the first valid transaction wins and the database uniqueness rule prevents a second live allocation. Driver-facing feasible slots are ordered by time and dock code, not shipment priority. The separate facility scheduling helper applies priority weights with deterministic timing tie-breakers; it does not reserve capacity.

Reason: The brief requires deterministic, business-reasonable ranking while also proving no double-booking under concurrency. These are different problems and must not be conflated.

Trade-off: The conversation flow does not currently arbitrate simultaneous requests by priority; a valid transaction can win the specific slot race. Priority applies only to the separate schedule proposal, so operations must not treat it as a reservation.

Evidence to produce: concurrency proof for slot-level integrity. The Phase 6 conversation scenario does not evaluate priority ordering; the scheduler helper is a separate proposal and needs its own focused scenario evidence.

Status: Implemented in the facility scheduling helper; priority weights are explicit. Not applied to the driver's time-ordered options.

## 8. What is the scheduling objective for a facility-level tool?

Answer: The facility scheduling helper is a non-binding proposal. It selects the earliest feasible dock start; for equal starts it prefers higher priority, then earlier ETA and shipment ID. In-progress unloads remain fixed. It compares priority-weighted waiting minutes (`wait × priority weight`), total and average waiting, and missed appointments as separate scorecard measures.

Reason: The brief says to start with simple rules and only use a heavier solver if it is justified. The required comparison has only three movable shipments once the in-progress unload is fixed. The greedy rule ties the FCFS scorecard in this case, so there is no evidence that a heavier optimizer would improve the result.

Trade-off: It is explainable but not globally optimal; the current case does not show improvement over FCFS. Separate scorecard values avoid hiding business trade-offs inside a made-up composite weight.

Evidence: `scenarios/phase8_scheduler_comparison.md` and `.json` compare the requested four shipments against FCFS and show SHP1002 fixed at dock D2 until its estimated finish.

Status: Implemented as a simple greedy proposal and compared with FCFS on the required snapshot case. The proposal does not write bookings; broader facility scenarios remain outstanding.

## 9. How do we handle stale options, cancellations, duplicate messages, and retries?

Answer: The conversation re-checks availability before taking an offered slot, and the engine's atomic hold can still reject a race loser. Cancels are retained as historical appointment records. The conversation suppresses identical driver text in the same thread for a five-minute simulated-time window. This is message deduplication, not full booking-request idempotency: the structured wrapper's request ID is not persisted as a retry key.

Reason: The brief explicitly calls out duplicate chat messages and stale options as first-class operational hazards.

Trade-off: Deduping reduces noise and prevents accidental rebooking, but it requires explicit handling of retries and careful message provenance metadata.

Evidence to produce: the scenario demonstrates an option becoming unavailable and being refreshed; a dedicated duplicate-message and booking-retry test is still outstanding.

Status: Fixed.

## 10. What happens when no feasible slot exists?

Answer: The system must not invent a slot, relax a rule, or silently hide the problem. It creates an escalation record, tags the thread as escalated, records the reason in the audit log, and tells the driver honestly that no safe automatic outcome exists.

Reason: The brief explicitly says “escalate rather than invent” and calls out no safe automatic decision as a human review case.

Trade-off: Some requests will be escalated more often than a purely auto-optimizing system would. That is the correct trade-off for safety and compliance.

Evidence to produce: zero-feasible-slot scenario run and a clear escalation record with reason context.

Status: Fixed.

## 11. What do we say when the preferred slot is not granted?

Answer: We give a plain-language reason, not a vague refusal. The reason should be operationally truthful: slot was taken, slot was blocked or invalid, the load is not compatible, or the facility rule requires approval. We then either refresh alternatives or escalate with a case reference.

Reason: The brief requires the driver-facing response to be understandable and not to hide the reason behind a generic error.

Trade-off: More verbose responses and a larger number of explanation steps, but much higher trust and lower chance of “I accepted but it was never really available.”

Evidence to produce: conversation-layer tests for refusal reasons and the scenario transcript output showing the response pattern.

Status: Fixed.

## 12. Which decisions require human approval or takeover?

Answer: Human approval is required for any case where the engine should not decide alone: no feasible slot, facility rule restrictions such as last-new-start-time, contradictory or incomplete data, driver/shipment ambiguity that remains unresolved, safety-related issues, or out-of-scope cases such as penalties and compensation. The system always reports what has happened and what the ops team needs to do next.

Reason: The brief’s “no autonomous safety decisions” and “escalate rather than invent” rules are explicit.

Trade-off: It increases the load on operations staff during spikes, but it protects correctness and avoids unsafe commitments.

Evidence to produce: escalation cases and the path from driver text to human handoff in the scenario run.

Status: Fixed.

## 13. What is the proof that the engine is safe under concurrency and retried requests?

Answer: The concurrency proof comes from SQLite write transactions and the partial unique index on active appointments for a slot. The thread-based race test demonstrates one successful hold and one clean `SLOT_TAKEN` loser. The conversation rechecks availability before holding a previously shown option. Chat deduplication is limited to identical text in a short window; durable request-key idempotency and process-level races are not yet proven.

Reason: The brief demands a deterministic engine and a concurrency proof. A prompt cannot provide that proof.

Trade-off: The code is more explicit and more mechanical than a natural-language-first approach, but that is exactly what makes the system safe under load.

Evidence to produce: `tests/test_concurrency.py` and the Phase 6 replay. The current proof covers threads with independent connections, not separate processes; dedicated idempotency and retry tests remain open.

Status: Fixed.

## Decision summary

The implemented design is intentionally conservative:
- Ask for missing facts instead of guessing
- Treat showing, holding, and confirming as distinct states
- Use database-level constraints as the real integrity proof
- Escalate when facts are contradictory, stale, or unsafe to decide alone
- Prefer explainability and deterministic logic over “smart” prompt behavior

This draft will be updated if the implementation forces a change, but the current working design follows the brief’s safety and determinism requirements.
