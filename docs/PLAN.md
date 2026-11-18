# Plan

Build milestone by milestone (agreed with the user): each milestone is tested, committed and summarised before the next starts.

- [x] **0 Foundation** - repo, CLAUDE.md, Compose, CI, Alembic, seed, DATA_AUDIT
  - [x] Monorepo layout, FastAPI core (config, db, logging, errors, security, idempotency)
  - [x] Reference schema models (18 tables) + migrations `0001`, `0002` (EXCLUDE, partial uniques, 4 views)
  - [x] Seed script SQLite -> PostgreSQL (all rows load, constraints hold)
  - [x] Docker Compose (postgres, redis, api, worker, web), `.env.example`
  - [x] CI workflow, docs/DATA_AUDIT.md, DECISIONS.md
  - [x] Next.js app builds with four portal shells
  - [ ] shadcn/ui, next-intl, TanStack Query, api-client generation (moved to Milestone 1)
- [x] **1 Identity and shell** - auth (login, rotation, lockout, CSRF, invite), RBAC matrix + scope isolation, audit hook + append-only log, settings, SSE (Redis Streams), web shell (i18n en/hi, theme, guards). Deferred: TOTP, password-reset email, email delivery (invite token returned by API), OIDC, shadcn CLI components (hand-rolled primitives), generated OpenAPI client
- [x] **2 Admin core** - facilities (+contacts, CSV import/export), carriers, drivers directory, shipments (create/edit/offer/cancel/timeline/CSV), audit + settings screens, Idempotency-Key support, 159 backend tests. Not browser-tested: create/edit forms, CSV dialogs, Hindi, dark mode
- [x] **3 Facility portal** - docks, slot generator/bulk/copy, dock events, rules (+history), day-schedule grid, pending confirmations, inbound, yard and gate, contacts, reports, facility home; 191 backend tests. Deferred to M4: drag-and-drop move, suggest-another-slot, held state, auto re-plan exceptions. Browser-checked: grid on seeded date only; other screens, Hindi, dark mode not
- [x] **4 Scheduling and booking engine** - find_options + ranking, holds/approve/suggest/keep/reject, expiry sweeper, move/cancel, claims-based DB integrity, outbox, metrics, escalation on no slot; 272 backend tests, docs/INTEGRITY_PROOF.md (14/14, zero double bookings). UI: drag-move + options picker (built, not browser-exercised). Left for later: ranking for competing requests is a tested function but has no endpoint yet (M6); AI never involved
- [x] **5 Carrier portal** - drivers/vehicles CRUD + CSV, WhatsApp verification flow (code queued for M8 delivery), offer accept/decline, assignment with compatibility blocks + warnings, reassign with reason, read-only tracker and slot-change feed, notifications (outbox projection + bell), dashboard, carrier reports. 357 backend tests. Browser-checked: carrier dashboard and tracker on seeded data; forms, CSV dialogs, Hindi, dark mode not
- [x] **6 Coordinator portal** - live inbox with soft locks, request detail + rule-based recommendation, approve/suggest/hold/reject/escalate with driver message templates, competing requests with override reason, holds (extend/release), escalations, conversation viewer with takeover/hand-back/reply, live board, shift handover, my activity; 393 backend tests. Browser-checked: inbox and conversation list on seeded data; request detail, takeover/reply, keyboard shortcuts, Hindi, dark mode not. Messages are queued (outbox), not delivered until M8; translation and AI wording M7
- [x] **7 AI platform** - single router `ai.run` with fallback chains, circuit breakers (Redis), key pools, budgets + alerts, PII masking, kill switches, graceful degradation, versioned prompts, evaluations (golden set), usage/cost, logs; admin screens; offline mock provider; 471 backend tests incl. router tests for every failure path. Browser-checked: routes + simulate-failure fallback; other AI screens not clicked through. No real provider has been called (no keys); golden-set variants and Hindi strings unreviewed
- [x] **8 WhatsApp and agent** - webhook (signed, deduped), processor (opt-in/out, verification codes, rate limit, takeover pause), Cloud API + simulator senders, 24 templates (en/hi/te), delivery outbox with retries, admin WhatsApp screens + simulator, LangGraph driver agent with deterministic guardrails and reviewed en/hi/te catalogue; decisions 67-87. Hindi/Telugu strings unreviewed; no real WhatsApp or AI provider called
- [ ] 9 Insights and optimiser
- [ ] 10 Hardening and delivery
