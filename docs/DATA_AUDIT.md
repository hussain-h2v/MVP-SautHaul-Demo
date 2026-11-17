# Data audit

Full findings and business handling rules are in [01_problem_definition_and_data_audit.md](01_problem_definition_and_data_audit.md); each is proven by a query in [`sql/audit/`](../sql/audit) (SQLite dialect, run against the snapshot).

| # | Issue | Proof | Handling in the platform |
|---|---|---|---|
| A | Slots overlap blocked/maintenance/breakdown events | `01_*.sql` | Feasibility rejects slots overlapping any live `dock_status_events` window |
| B | Cancelled / no-show appointments are history, not capacity | `02_*.sql` | Partial unique indexes ignore them; never counted as occupied |
| C | `PENDING_CONFIRMATION` rows are holds, not promises | `03_*.sql` | Re-validate at confirmation; only CONFIRMED is promised |
| D | Drivers with several active shipments | `04_*.sql` | Agent asks with buttons, never guesses |
| E | Conflicting ETA sources | `05_*.sql` | Latest non-superseded ETA wins; history kept |
| F | Dock/load compatibility not DB-enforced | `06_*.sql` | Enforced in scheduling service |
| G | Duplicate chat messages / failed operational messages / contacts without email | `07_*.sql` | Dedupe by WhatsApp message id; FAILED never counts as confirmation |
| H | Check-in dock can differ from planned dock | `08_*.sql` | Human-review trigger |
| I | Existing unique indexes do not cover NULL-shipment threads, retries | `09_*.sql` | Idempotency keys + conversation-level resolution |

**What the two reference rules do not cover**: they police only active appointment states (not history), cannot stop overlapping slot windows on a dock (now covered by the new EXCLUDE constraint), and say nothing about holds, duplicates or compatibility.

**Platform seed note**: all 18 tables loaded into PostgreSQL with every CHECK, FK, partial unique index and the new EXCLUDE constraint active, so the snapshot itself satisfies the stricter rules (no overlapping slots on any dock). Row counts: slots 106, appointments 26, shipments 21, chat messages 150.
