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
12. **Layout**: two top-level folders, `backend/` (was apps/api) and `frontend/` (was apps/web), per user request; `infra/` and `docs/` stay at root.
13. **Auth**: access JWT (15 min) carries a session id checked against `sessions` on every request, so logout / force-logout / disable take effect immediately; refresh token rotates on each refresh. CSRF is double-submit (`csrf_token` cookie + `X-CSRF-Token`). Frontend reaches the API same-origin via a Next rewrite.
14. **Invites**: no email service yet, so `POST /users` returns the one-time `invite_token` to the admin. TOTP and self-service password reset are deferred (planned M10 hardening).
15. **Audit**: one SQLAlchemy session hook records every ORM insert/update/delete with actor, IP and trace id; secrets are masked. Raw-SQL writes (seed scripts) bypass it by design.
16. **Events**: SSE is backed by a Redis Stream (resume with Last-Event-ID); each event carries facility/carrier scope and is filtered per principal.
17. **Hold TTL** default is 15 min per the platform spec (the prototype used 5).
18. **Test hashing** uses cheap argon2 parameters when `ENV=test`.
19. **Shipment creation** leaves carrier/driver/vehicle empty (columns made nullable) with `offer_status` draft -> offered -> accepted/declined; carrier users never see drafts. Default planned ETA = facility opening time on the requested date (next day if none).
20. **Cancelling a shipment that holds an active appointment is blocked (409)** until the booking service (M4) can release the slot safely.
21. **Idempotency-Key**: middleware replays 2xx JSON responses per (session, method, path, key) for 24h via Redis.
22. **CSV import** is atomic (any bad row rejects the whole file) with a dry-run preview; exports neutralise spreadsheet formula injection.
23. Frontend dev port is **2000** (user request); the API stays on 8000.
