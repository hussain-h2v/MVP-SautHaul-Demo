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
- [ ] 6 Coordinator portal
- [ ] 7 AI platform
- [ ] 8 WhatsApp and agent
- [ ] 9 Insights and optimiser
- [ ] 10 Hardening and delivery
