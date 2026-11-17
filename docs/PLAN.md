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
- [ ] 1 Identity and shell - auth, users, roles, scopes, audit mechanism, settings, UI shell, permission-matrix tests
- [ ] 2 Admin core
- [ ] 3 Facility portal
- [ ] 4 Scheduling and booking engine + INTEGRITY_PROOF
- [ ] 5 Carrier portal
- [ ] 6 Coordinator portal
- [ ] 7 AI platform
- [ ] 8 WhatsApp and agent
- [ ] 9 Insights and optimiser
- [ ] 10 Hardening and delivery
