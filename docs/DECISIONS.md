# Decisions and assumptions (platform build)

Product-behaviour decisions (what to collect, hold vs confirm, escalation, etc.) from the prototype are in `02_decision_register.md` and carry over; this file records build decisions.

1. **No `/reference` folder was supplied** (no brief PDF, seed SQL, data dictionary, ER diagram). Schema was taken by introspecting `data/setuhaul_freight_operations.db`; prototype notes live in `docs/`.
2. **Seed source** is that SQLite file. It is a *working copy* (extra tables `agent_holds`, `agent_audit_log`; more rows than the pristine snapshot: 150 chat messages, 26 appointments, 28 ETA updates). It is seeded as-is; the two extra tables are not carried (superseded by `slot_holds` and `audit_log` in later milestones).
3. **Keys**: surrogate UUID PKs (deterministic uuid5 in the seed, so re-seeding is idempotent); original ids (`SHP1002`, `THR003`, ...) kept as unique `code`. Tables without a business id (eta_updates, contacts, rules, dock events, check-ins, operational messages) have no `code`.
4. **Booleans** are native `boolean`; text timestamps (already ISO with +05:30) become `timestamptz`; `open_time/close_time` become `time`.
5. **Integrity** added beyond the reference: `EXCLUDE USING gist (dock_id =, tstzrange(start,end) &&)` on slots (needs `btree_gist`); partial unique indexes recreated with boolean `is_current`.
6. **Views** recreated against UUID keys and expose `*_code` columns for readability.
7. **No cross-module ORM relationships** to keep module boundaries (see CLAUDE.md).
8. **Drivers seeded as WhatsApp-verified** (`whatsapp_number = phone`, opted in, `en`) so the simulator works on seed data; real onboarding uses the verification flow.
9. **Python**: target 3.12 in Docker; local machine has 3.14, so all Python commands run in containers. `httpx` pinned `<0.28` for litellm compatibility.
10. **`chat_threads.taken_over_by_user_id`** is deferred to Milestone 1 (needs `users`).
11. **Pace**: milestone-by-milestone, per user choice.
